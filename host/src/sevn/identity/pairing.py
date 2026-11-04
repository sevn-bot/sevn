"""One-time pairing tickets and ``pair.complete`` (plan 0055 D1).

A ticket is 32 random bytes (base64url) with an 8-character Crockford short code;
both are one credential and either use spends it. Only SHA-256 digests of the
ticket and of the code are stored. A ticket lives 10 minutes and is bound to this
host's id.

Only the short code can be guessed, so only it is rate limited. ``pair.complete``
is reachable before authentication, so a limit on the full ticket would let anyone
who can reach the port lock the owner out. A wrong code counts against every
unexpired ticket's code, which stops working after 5 failures, and 20 failures in a
rolling hour refuse every code on the host until the hour has passed. A valid full
ticket (the QR code or link) still pairs after that, and a wrong one counts for
nothing.

All time reads go through this module's ``utcnow`` so tests can move the clock.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from urllib.parse import urlencode

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.config import HttpSettings
from sevn.contracts.errors import ErrorCode, ProtocolError
from sevn.contracts.frames import PairComplete, Paired
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.identity.devices import PLATFORM_LIMIT, clean_name
from sevn.identity.handshake import b64u, unb64u
from sevn.identity.keys import HostIdentity
from sevn.log import logger
from sevn.protocol.errors import Scope
from sevn.store.db import utcnow
from sevn.store.models import Device, PairingAttempt, PairingTicket

__all__ = [
    "CROCKFORD",
    "TICKET_TTL",
    "PairingError",
    "Ticket",
    "complete",
    "default_direct_url",
    "pair_uri",
    "start",
    "utcnow",
]

TICKET_TTL = timedelta(minutes=10)
TICKET_FAILURES = 5
HOST_FAILURES_PER_HOUR = 20
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CODE_LENGTH = 8
_CODE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{8}$")
_WINDOW = timedelta(hours=1)
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})
_BAD_TICKET = "invalid pairing ticket"
_RATE_LIMITED = "too many pairing attempts"


class PairingError(ProtocolError):
    """A refused pairing step. Every ticket failure has the same message."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(code, message)


@dataclass(frozen=True, slots=True)
class Ticket:
    """A fresh ticket. The only place the ticket and code exist in clear."""

    ticket: str
    short_code: str
    qr_uri: str
    expires_at: datetime
    scope: Scope

    def __repr__(self) -> str:
        return f"Ticket(scope={self.scope!r}, expires_at={self.expires_at.isoformat()})"


async def start(
    *,
    identity: HostIdentity,
    http: HttpSettings,
    scope: Scope = "member",
    name: str | None = None,
    direct_url: str | None = None,
) -> Ticket:
    """Mint a ticket. Who may mint which scope is the caller's check."""
    ticket = secrets.token_urlsafe(32)
    code = "".join(secrets.choice(CROCKFORD) for _ in range(_CODE_LENGTH))
    now = utcnow()
    expires_at = now + TICKET_TTL
    label = None if name is None else clean_name(name) or None
    async with open_session() as session:
        session.add(
            PairingTicket(
                id=new_id("ptk_"),
                host_id=identity.host_id,
                ticket_hash=_digest(ticket),
                code_hash=_digest(code),
                scope=scope,
                name=label,
                created_at=now,
                expires_at=expires_at,
                used_at=None,
                failures=0,
            )
        )
        await session.commit()
    logger.info("pairing ticket issued for scope {}", scope)
    direct = direct_url if direct_url is not None else default_direct_url(http)
    return Ticket(
        ticket=ticket,
        short_code=code,
        qr_uri=pair_uri(identity, ticket, direct),
        expires_at=expires_at,
        scope=scope,
    )


def pair_uri(identity: HostIdentity, ticket: str, direct_url: str | None) -> str:
    """``sevn://pair?h=<host_id>&k=<host_pubkey_fp>&t=<ticket>[&d=<direct_url>]``."""
    query: list[tuple[str, str]] = [
        ("h", identity.host_id),
        ("k", identity.host_pubkey_fp),
        ("t", ticket),
    ]
    if direct_url:
        query.append(("d", direct_url))
    return "sevn://pair?" + urlencode(query)


def default_direct_url(http: HttpSettings) -> str | None:
    """The first non-loopback allowed host (config, then ``SEVN_ALLOWED_HOSTS``) as a URL.

    ``wss://`` when ``http.public_scheme = "https"`` (``tailscale serve``), else ``ws://``.
    """
    scheme = "wss" if http.public_scheme == "https" else "ws"
    for cleaned in http.merged_allowed_hosts():
        if _host_part(cleaned).lower() in _LOOPBACK_HOSTS:
            continue
        return f"{scheme}://{cleaned}/ws"
    return None


async def complete(frame: PairComplete, *, identity: HostIdentity) -> Paired:
    """Spend the ticket and store the device. Raises ``PairingError`` on refusal."""
    now = utcnow()
    is_code = _CODE.fullmatch(frame.ticket.strip().upper()) is not None
    async with open_session() as session:
        stale = delete(PairingAttempt).where(PairingAttempt.created_at < now - _WINDOW)
        await session.execute(stale)
        if is_code and await _recent_failures(session, now) >= HOST_FAILURES_PER_HOUR:
            await session.commit()
            logger.warning("pairing refused: host attempt limit reached")
            raise PairingError("rate_limited", _RATE_LIMITED)
        pubkey = _device_key(frame.device_pubkey_ed25519)
        row = await _find(session, frame.ticket, identity.host_id, now)
        claimed = False
        if row is not None:
            result = cast(
                "CursorResult[Any]",
                await session.execute(
                    update(PairingTicket)
                    .where(PairingTicket.id == row.id)
                    .where(PairingTicket.used_at.is_(None))
                    .values(used_at=now)
                ),
            )
            claimed = result.rowcount == 1
        if row is None or not claimed:
            if is_code:
                await _record_failure(session, identity.host_id, now)
            await session.commit()
            logger.warning("pairing refused: invalid ticket")
            raise PairingError("unauthorized", _BAD_TICKET)
        scope = cast("Scope", row.scope)
        device = Device(
            id=new_id("dev_"),
            name=clean_name(frame.device_name) or "Device",
            platform=clean_name(frame.platform, limit=PLATFORM_LIMIT) or "unknown",
            pubkey_ed25519=b64u(pubkey),
            # D2: stays NULL until plan 0080 uses it.
            pubkey_x25519=None,
            scope=scope,
            created_at=now,
            last_seen=None,
            revoked_at=None,
        )
        session.add(device)
        session.add(PairingAttempt(id=new_id("pat_"), ok=True, created_at=now))
        await session.commit()
    logger.info("device {} paired with scope {}", device.id, scope)
    return Paired(
        t="paired",
        device_id=device.id,
        host_id=identity.host_id,
        host_pubkey=b64u(identity.public_key),
        scope=scope,
    )


async def _find(
    session: AsyncSession, presented: str, host_id: str, now: datetime
) -> PairingTicket | None:
    value = presented.strip()
    code = value.upper()
    query = (
        select(PairingTicket)
        .where(PairingTicket.host_id == host_id)
        .where(PairingTicket.used_at.is_(None))
        .order_by(PairingTicket.created_at.desc())
    )
    if _CODE.fullmatch(code):
        query = query.where(
            PairingTicket.code_hash == _digest(code),
            PairingTicket.failures < TICKET_FAILURES,
        )
    else:
        query = query.where(PairingTicket.ticket_hash == _digest(value))
    rows = await session.scalars(query)
    for row in rows:
        if row.expires_at > now:
            return row
    return None


async def _recent_failures(session: AsyncSession, now: datetime) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(PairingAttempt)
        .where(PairingAttempt.ok.is_(False))
        .where(PairingAttempt.created_at > now - _WINDOW)
    )
    return int(count or 0)


async def _record_failure(session: AsyncSession, host_id: str, now: datetime) -> None:
    session.add(PairingAttempt(id=new_id("pat_"), ok=False, created_at=now))
    await session.execute(
        update(PairingTicket)
        .where(PairingTicket.host_id == host_id)
        .where(PairingTicket.used_at.is_(None))
        .where(PairingTicket.expires_at > now)
        .values(failures=PairingTicket.failures + 1)
    )


def _device_key(encoded: str) -> bytes:
    try:
        raw = unb64u(encoded)
        Ed25519PublicKey.from_public_bytes(raw)
    except ValueError as exc:
        raise PairingError("invalid_params", "invalid device key") from exc
    return raw


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _host_part(entry: str) -> str:
    if entry.startswith("["):
        end = entry.find("]")
        return entry if end == -1 else entry[: end + 1]
    if entry.count(":") == 1:
        return entry.split(":", 1)[0]
    return entry
