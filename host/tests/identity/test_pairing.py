"""Pairing tickets, short codes and ``pair.complete`` (plan 0055 D1).

Contracts pinned here (see ``.ignorelocal/test-plans/0055-direct-multi-host.md``):
- ``pairing.start(name?, scope = member, direct_url?, op_id)``: mutating, ``scope="owner"``,
  returns ``{ticket, qr_uri, short_code, expires_at}``; the op log keeps no ticket.
- ``sevn.identity.pairing.complete(PairComplete, identity=HostIdentity) -> Paired``; failures
  raise ``ProtocolError`` (``unauthorized`` / ``rate_limited``).
- Pairing reads time through ``sevn.identity.pairing.utcnow`` (tests move it).
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from support.memory import MemoryHost, collect_until_close, memory_host, send_frame
from support.pairing import (
    Device,
    b64u,
    call,
    complete,
    complete_frame,
    new_device,
    op_id,
    owner_client,
    pair_device,
    register_methods,
    start_pairing,
)

W3 = pytest.mark.xfail(strict=False, reason="green after W3")

SHORT_CODE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{8}$")
BAD_TICKET = "invalid pairing ticket"
RATE_LIMITED = "too many pairing attempts"
OWNER_NEEDS_LOOPBACK = "owner tickets need a loopback owner session"


@asynccontextmanager
async def _host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, http: str = ""
) -> AsyncIterator[MemoryHost]:
    async with memory_host(tmp_path, monkeypatch, config_extra=http) as host:
        register_methods()
        yield host


def _move_clock(monkeypatch: pytest.MonkeyPatch, offset: timedelta) -> None:
    import sevn.identity.pairing as pairing

    base = datetime.now(UTC)
    monkeypatch.setattr(pairing, "utcnow", lambda: base + offset)


def _near_miss(ticket: str) -> str:
    """The same ticket with one character changed (counts against that ticket in any layout)."""
    index = len(ticket) - 5
    swapped = "A" if ticket[index] != "A" else "B"
    return ticket[:index] + swapped + ticket[index + 1 :]


async def _expect_refused(host: MemoryHost, ticket: str, code: str, message: str) -> None:
    from sevn.contracts.errors import ProtocolError

    with pytest.raises(ProtocolError) as exc:
        await complete(host, complete_frame(ticket, new_device()))
    assert exc.value.code == code
    assert exc.value.message == message


async def _dispatch(session: Any, method: str, params: dict[str, Any]) -> Any:
    from sevn.contracts.frames import Req
    from sevn.protocol.registry import dispatch

    return await dispatch(session, Req(t="req", id="1", m=method, p=params))


# --- pairing.start ---------------------------------------------------------------------------


@pytest.mark.parametrize("scope", ["member", "read_only"])
async def test_start_is_owner_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    from sevn.protocol.session import Session

    async with _host(tmp_path, monkeypatch) as host:
        session = Session.for_test(scope=scope, loopback=True, hub=host.hub)  # type: ignore[call-arg]
        res = await _dispatch(session, "pairing.start", {"op_id": op_id()})
        assert res.e is not None
        assert res.e.code == "forbidden"
        tickets = await asyncio.to_thread(_rows, tmp_path / "sevn.db", "pairing_tickets")
        assert tickets == []


async def test_owner_ticket_needs_loopback_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.protocol.session import Session

    async with _host(tmp_path, monkeypatch) as host:
        remote_owner = Session.for_test(  # type: ignore[call-arg]
            scope="owner", loopback=False, hub=host.hub, device_id="dev_remote_owner"
        )
        refused = await _dispatch(
            remote_owner, "pairing.start", {"scope": "owner", "op_id": op_id()}
        )
        assert refused.e is not None
        assert refused.e.code == "forbidden"
        assert refused.e.message == OWNER_NEEDS_LOOPBACK
        # A remote owner may still hand out lower scopes.
        member = await _dispatch(
            remote_owner, "pairing.start", {"scope": "member", "op_id": op_id()}
        )
        assert member.e is None and member.r is not None
        assert isinstance(member.r["ticket"], str) and member.r["ticket"]
        # The loopback owner may mint an owner ticket, and it pairs an owner device.
        owner = await owner_client(host)
        device = await pair_device(host, owner, scope="owner")
        assert device.scope == "owner"


async def test_start_returns_ticket_code_uri_and_ten_minute_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        before = datetime.now(UTC)
        started = await start_pairing(owner)
        assert set(started) >= {"ticket", "qr_uri", "short_code", "expires_at"}
        assert len(started["ticket"]) >= 32
        assert SHORT_CODE.fullmatch(started["short_code"]), started["short_code"]
        expires = datetime.fromisoformat(started["expires_at"])
        assert expires.tzinfo is not None
        lifetime = expires - before
        assert timedelta(minutes=9, seconds=55) <= lifetime <= timedelta(minutes=10, seconds=5)
        query = parse_qs(urlsplit(started["qr_uri"]).query)
        assert started["qr_uri"].startswith("sevn://pair?")
        assert query["h"] == [host.hub.identity.host_id]
        assert query["k"] == [host.hub.identity.host_pubkey_fp]
        assert query["t"] == [started["ticket"]]
        # The default scope is member.
        paired = await complete(host, complete_frame(started["ticket"], new_device()))
        assert paired.scope == "member"


async def test_start_rejects_unknown_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        res = await call(owner, "pairing.start", {"scope": "admin", "op_id": op_id()})
        assert res["e"]["code"] == "invalid_params"
        assert res["e"]["data"]["errors"][0]["loc"] == ["scope"]


# --- tickets ---------------------------------------------------------------------------------


async def test_ticket_single_use_and_expires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        once = await start_pairing(owner)
        await complete(host, complete_frame(once["ticket"], new_device()))
        await _expect_refused(host, once["ticket"], "unauthorized", BAD_TICKET)

        still_valid = await start_pairing(owner)
        expired = await start_pairing(owner)
        _move_clock(monkeypatch, timedelta(minutes=9, seconds=30))
        await complete(host, complete_frame(still_valid["ticket"], new_device()))
        _move_clock(monkeypatch, timedelta(minutes=10, seconds=30))
        await _expect_refused(host, expired["ticket"], "unauthorized", BAD_TICKET)


async def test_ticket_stored_hashed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """K-CANARY: a ticket and its short code exist only as SHA-256 on the host."""
    from support.canary import canary

    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        with canary() as probe:
            params = {"op_id": op_id(), "name": "Phone"}
            first = await call(owner, "pairing.start", params)
            started = first["r"]
            ticket, code = started["ticket"], started["short_code"]
            # A replay of the same op_id must not hand the ticket back from the op log.
            replay = await call(owner, "pairing.start", params)
            assert replay["r"]["ticket"] != ticket
            assert replay["r"]["short_code"] != code
            probe.assert_absent(ticket)
            probe.assert_absent(code)
        rows = await asyncio.to_thread(_rows, tmp_path / "sevn.db", "pairing_tickets")
        assert len(rows) == 1
        text = repr(rows)
        assert ticket not in text
        assert code not in text and code.lower() not in text
        assert hashlib.sha256(ticket.encode("utf-8")).hexdigest() in text
        # The stored form still pairs.
        await complete(host, complete_frame(ticket, new_device()))


async def test_short_code_maps_to_ticket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        upper = await start_pairing(owner, scope="read_only")
        paired = await complete(host, complete_frame(upper["short_code"], new_device()))
        assert paired.scope == "read_only"
        # The code and the ticket are one credential: either use spends both.
        await _expect_refused(host, upper["ticket"], "unauthorized", BAD_TICKET)
        await _expect_refused(host, upper["short_code"], "unauthorized", BAD_TICKET)

        lower = await start_pairing(owner)
        typed = lower["short_code"].lower()
        paired_lower = await complete(host, complete_frame(typed, new_device()))
        assert paired_lower.scope == "member"


_HTTPS_HOSTS = (
    '\n[http]\nallowed_hosts = ["localhost:8787", "mac.tailnet.ts.net"]\npublic_scheme = "https"\n'
)
_HTTP_HOSTS = '\n[http]\nallowed_hosts = ["127.0.0.1:8787", "100.101.102.103:8787"]\n'


@pytest.mark.parametrize(
    ("http", "scheme", "netloc"),
    [
        (_HTTPS_HOSTS, "wss", "mac.tailnet.ts.net"),
        (_HTTP_HOSTS, "ws", "100.101.102.103:8787"),
    ],
    ids=["tailscale-serve-https", "overlay-plain-ws"],
)
async def test_qr_uri_has_direct_url_from_allowed_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, http: str, scheme: str, netloc: str
) -> None:
    """W2 reads ``http.allowed_hosts`` and ``http.public_scheme`` (D5 fields) for the default."""
    async with _host(tmp_path, monkeypatch, http) as host:
        owner = await owner_client(host)
        started = await start_pairing(owner)
        query = parse_qs(urlsplit(started["qr_uri"]).query)
        direct = urlsplit(query["d"][0])
        assert direct.scheme == scheme
        assert direct.netloc == netloc
        assert direct.path in {"", "/", "/ws"}
        explicit = await start_pairing(owner, direct_url="wss://linux.tailnet.ts.net/ws")
        explicit_query = parse_qs(urlsplit(explicit["qr_uri"]).query)
        assert explicit_query["d"] == ["wss://linux.tailnet.ts.net/ws"]


async def test_qr_uri_without_remote_host_has_no_direct_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        started = await start_pairing(owner)
        assert "d" not in parse_qs(urlsplit(started["qr_uri"]).query)


# --- rate limits -----------------------------------------------------------------------------


@pytest.mark.parametrize(("failures", "burned"), [(4, False), (5, True)])
async def test_five_failures_burn_ticket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failures: int, burned: bool
) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        started = await start_pairing(owner)
        for _ in range(failures):
            await _expect_refused(host, _near_miss(started["ticket"]), "unauthorized", BAD_TICKET)
        if burned:
            await _expect_refused(host, started["ticket"], "unauthorized", BAD_TICKET)
        else:
            paired = await complete(host, complete_frame(started["ticket"], new_device()))
            assert paired.device_id.startswith("dev_")


async def test_host_rate_limit_20_per_hour(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        for _ in range(19):
            await _expect_refused(host, secrets.token_urlsafe(32), "unauthorized", BAD_TICKET)
        fresh = await start_pairing(owner)
        await complete(host, complete_frame(fresh["ticket"], new_device()))
        await _expect_refused(host, secrets.token_urlsafe(32), "unauthorized", BAD_TICKET)
        # 20 failures this hour: even a valid ticket is refused now.
        blocked = await start_pairing(owner)
        await _expect_refused(host, blocked["ticket"], "rate_limited", RATE_LIMITED)
        _move_clock(monkeypatch, timedelta(minutes=61))
        later = await start_pairing(owner)
        paired = await complete(host, complete_frame(later["ticket"], new_device()))
        assert paired.device_id.startswith("dev_")


# --- pair.complete ---------------------------------------------------------------------------


async def test_complete_stores_device_and_returns_paired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        started = await start_pairing(owner, scope="member", name="Kitchen phone")
        device: Device = new_device()
        paired = await complete(
            host, complete_frame(started["ticket"], device, name="Pixel", platform="android")
        )
        identity = host.hub.identity
        assert paired.t == "paired"
        assert paired.device_id.startswith("dev_")
        assert paired.host_id == identity.host_id
        assert paired.host_pubkey == b64u(identity.public_key)
        assert paired.scope == "member"
        listed = await call(owner, "devices.list", {})
        rows = {row["id"]: row for row in listed["r"]["devices"]}
        stored = rows[paired.device_id]
        assert stored["name"] == "Pixel"
        assert stored["platform"] == "android"
        assert stored["scope"] == "member"
        assert stored["revoked_at"] is None
        assert stored["last_seen"] is None
        devices = await asyncio.to_thread(_rows, tmp_path / "sevn.db", "devices")
        assert device.pubkey in repr(devices)


async def test_complete_refuses_a_malformed_device_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.contracts.errors import ProtocolError

    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        started = await start_pairing(owner)
        frame = complete_frame(started["ticket"], new_device())
        frame["device_pubkey_ed25519"] = b64u(b"\x01" * 31)
        with pytest.raises((ProtocolError, ValueError)):
            await complete(host, frame)
        assert await asyncio.to_thread(_rows, tmp_path / "sevn.db", "devices") == []


@W3
async def test_complete_stores_device_and_replies_paired_then_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Over a direct connection ``pair.complete`` is the first frame after ``hello`` (D1)."""
    from support.pairing import hello

    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        started = await start_pairing(owner, scope="read_only")
        client, _session = host.open_remote()
        device = new_device()
        await send_frame(client, hello("dev_unpaired"))
        await send_frame(client, complete_frame(started["ticket"], device, name="Tablet"))
        frames, closed = await collect_until_close(client)
        paired = [frame for frame in frames if frame.get("t") == "paired"]
        assert len(paired) == 1, frames
        assert paired[0]["host_id"] == host.hub.identity.host_id
        assert paired[0]["scope"] == "read_only"
        assert paired[0]["device_id"].startswith("dev_")
        assert all(frame.get("t") != "welcome" for frame in frames)
        assert (closed.code, closed.reason) == (1000, "paired")
        listed = await call(owner, "devices.list", {})
        assert paired[0]["device_id"] in {row["id"] for row in listed["r"]["devices"]}


@W3
async def test_pair_complete_with_a_bad_ticket_closes_4001(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from support.pairing import hello

    async with _host(tmp_path, monkeypatch) as host:
        client, _session = host.open_remote()
        await send_frame(client, hello("dev_unpaired"))
        await send_frame(client, complete_frame(secrets.token_urlsafe(32), new_device()))
        frames, closed = await collect_until_close(client)
        assert closed.code == 4001
        assert all(frame.get("t") not in {"paired", "welcome"} for frame in frames)


# --- sevn pair (CLI) -------------------------------------------------------------------------


def test_cli_pair_prints_uri_and_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    asyncio.run(_with_host(tmp_path, monkeypatch, lambda _host: _noop()))
    from sevn.cli import app

    result = CliRunner().invoke(app, ["pair", "--scope", "member", "--home", str(tmp_path)])
    assert result.exit_code == 0, result.output
    uri = re.search(r"sevn://pair\?\S+", result.output)
    assert uri is not None, result.output
    codes = [
        word for word in re.findall(r"[0-9A-Z]{8}", result.output) if SHORT_CODE.fullmatch(word)
    ]
    assert codes, result.output
    ticket = parse_qs(urlsplit(uri.group(0)).query)["t"][0]

    async def _complete(host: MemoryHost) -> None:
        paired = await complete(host, complete_frame(codes[0], new_device()))
        assert paired.scope == "member"
        await _expect_refused(host, ticket, "unauthorized", BAD_TICKET)

    asyncio.run(_with_host(tmp_path, monkeypatch, _complete))


async def _noop() -> None:
    return None


async def _with_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: Callable[[MemoryHost], Any],
) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        await body(host)


def _rows(db: Path, table: str) -> list[tuple[object, ...]]:
    with sqlite3.connect(db) as connection:
        present = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        if present is None:
            raise AssertionError(f"table {table} is missing")
        return connection.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
