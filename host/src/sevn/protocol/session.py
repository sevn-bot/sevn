"""Handshake and per-session outbound queue (D5-D7, D12).

A loopback session authenticates with the loopback token or cookie and is the
owner. Any other session (plan 0055 D3) never takes those paths: after ``hello``
it gets a ``challenge`` signed by the host over a fresh nonce and the origin the
client dialled, and must answer with a paired device's signature. Its scope is
that device's scope. ``pair.complete`` is the one other frame such a session may
send before ``auth``.
"""

from __future__ import annotations

import asyncio
import enum
import hmac
import json
import secrets
from collections import deque
from collections.abc import Coroutine, Iterable
from contextlib import suppress
from typing import Self, cast
from urllib.parse import urlsplit

from sevn.contracts.errors import ProtocolError
from sevn.contracts.frames import (
    AuthDevice,
    AuthToken,
    Challenge,
    FrameError,
    Hello,
    PairComplete,
    Req,
    Welcome,
    dump,
    parse,
)
from sevn.identity import devices, handshake, pairing
from sevn.log import logger
from sevn.protocol import HOST_CAPS, PROTOCOL_VERSION
from sevn.protocol.errors import (
    CLOSE_SLOW,
    CLOSE_UNAUTHORIZED,
    CLOSE_VERSION,
    REASON_SLOW,
    REASON_UNAUTHORIZED,
    REASON_VERSION,
    Scope,
)
from sevn.protocol.hub import Hub
from sevn.protocol.registry import dispatch, error_res
from sevn.transports.base import Connection, ConnectionClosed

_HANDSHAKE_DEADLINE_S = 10.0
_ORIGIN_SCHEMES = frozenset({"ws", "wss"})
_REASON_PAIRED = "paired"
_SIGNATURE_BYTES = 64  # an Ed25519 signature


class _Phase(enum.Enum):
    HELLO = "hello"
    AUTH = "auth"
    READY = "ready"
    # ``paired`` is queued; the session closes once it is sent.
    PAIRED = "paired"


class Session:
    """One protocol session on top of a ``Connection``."""

    scope: Scope
    hub: Hub
    # Plan 0055: whether the transport saw the local machine as the peer (only a
    # loopback session may use the token or cookie), and the paired device a
    # non-loopback session authenticated as.
    loopback: bool
    device_id: str | None

    def __init__(
        self,
        connection: Connection,
        hub: Hub,
        *,
        token: str,
        queue_limit: int,
        cookie: str | None = None,
        loopback: bool = False,
        allowed_hosts: Iterable[str] = (),
    ) -> None:
        self._connection = connection
        self.hub = hub
        self.scope = "read_only"
        self.loopback = loopback
        self.device_id = None
        self._token = token
        self._queue_limit = queue_limit
        self._phase = _Phase.HELLO
        self._allowed_hosts = frozenset(
            entry.strip().lower() for entry in allowed_hosts if entry.strip()
        )
        self._claimed_device = ""
        self._origin = ""
        self._nonce = b""
        # Set when ``hello.origin`` is missing or not allowed: every answer is refused.
        self._origin_refused = False
        self._cookie_ok = False
        self._cookie_rejected = False
        # A non-loopback session never looks at the cookie (D4).
        if cookie is not None and loopback:
            if _same(cookie, token):
                self._cookie_ok = True
            else:
                self._cookie_rejected = True
        self._pending: deque[str] = deque()
        self._deferred: list[str] = []
        self._held: list[str] = []
        self._hold_live = False
        self._replaying = False
        self._wake = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()
        self._in_request = False
        self._closing = False
        self._closed = False
        self._attached = False
        self._flushed = asyncio.Event()

    @classmethod
    def for_test(
        cls,
        *,
        scope: Scope,
        loopback: bool = True,
        hub: Hub | None = None,
        device_id: str | None = None,
    ) -> Self:
        session = cls.__new__(cls)
        session.scope = scope
        session.loopback = loopback
        session.device_id = device_id
        if hub is not None:
            session.hub = hub
        return session

    async def run(self) -> None:
        sender = asyncio.create_task(self._send_loop())
        deadline = asyncio.create_task(self._handshake_deadline())
        try:
            await self._receive_loop()
        finally:
            deadline.cancel()
            sender.cancel()
            with suppress(asyncio.CancelledError, ConnectionClosed):
                await sender
            with suppress(asyncio.CancelledError):
                await deadline
            if not self._closed:
                with suppress(Exception):
                    await self.close(1000, "closed")

    async def _handshake_deadline(self) -> None:
        await asyncio.sleep(_HANDSHAKE_DEADLINE_S)
        if self._phase is not _Phase.READY and not self._closed:
            await self.close(1002, "handshake timeout")

    async def close(self, code: int, reason: str) -> None:
        if self._closed:
            return
        self._closed = True
        self._closing = True
        self._pending.clear()
        self._wake.set()
        self._flushed.set()
        attached = self._attached
        self._attached = False
        if self.device_id is not None:
            self.hub.unbind_device(self.device_id, self)
        await self._connection.close(code, reason)
        if attached:
            await self.hub.detach(self)

    def deliver(self, frame: str) -> None:
        if self._closing or self._phase is not _Phase.READY:
            return
        if self._hold_live and not self._replaying:
            self._held.append(frame)
            return
        if self._in_request:
            self._deferred.append(frame)
            return
        self.enqueue(frame)

    def hold_live(self) -> None:
        self._hold_live = True

    def replay(self, frame: str) -> None:
        self._replaying = True
        try:
            self.deliver(frame)
        finally:
            self._replaying = False

    def release_live(self, high_water: int) -> None:
        self._hold_live = False
        held = self._held
        self._held = []
        for frame in held:
            seq = _evt_seq(frame)
            if seq is not None and seq <= high_water:
                continue
            self.deliver(frame)

    def enqueue(self, text: str) -> None:
        if self._closing:
            return
        if len(self._pending) >= self._queue_limit:
            self._closing = True
            self._spawn(self.close(CLOSE_SLOW, REASON_SLOW))
            return
        self._pending.append(text)
        self._wake.set()

    async def _receive_loop(self) -> None:
        while not self._closed:
            try:
                raw = await self._connection.recv_text()
            except ConnectionClosed:
                return
            try:
                frame = parse(raw)
            except FrameError:
                await self.close(1002, "protocol error")
                return
            await self._on_frame(frame)

    async def _on_frame(self, frame: object) -> None:
        if self._phase is _Phase.PAIRED:
            return
        if isinstance(frame, Hello) and self._phase is _Phase.HELLO:
            await self._on_hello(frame)
            return
        if not self.loopback and self._phase is _Phase.AUTH:
            if isinstance(frame, AuthDevice):
                await self._on_device_auth(frame.device_sig)
                return
            if isinstance(frame, PairComplete):
                await self._on_pair_complete(frame)
                return
            if isinstance(frame, AuthToken):
                await self.close(CLOSE_UNAUTHORIZED, REASON_UNAUTHORIZED)
                return
        if isinstance(frame, AuthToken) and self._phase is _Phase.AUTH:
            await self._on_auth(frame.token)
            return
        if isinstance(frame, AuthDevice) and self._phase is _Phase.AUTH:
            await self.close(CLOSE_UNAUTHORIZED, REASON_UNAUTHORIZED)
            return
        if isinstance(frame, Req):
            if self._phase is not _Phase.READY:
                self.enqueue(
                    dump(error_res(frame.id, ProtocolError("protocol_error", "not authenticated")))
                )
                return
            await self._on_req(frame)
            return
        if self._phase is not _Phase.READY:
            await self.close(1002, "protocol error")

    async def _on_hello(self, hello: Hello) -> None:
        if not _compatible(hello.proto):
            await self.close(CLOSE_VERSION, REASON_VERSION)
            return
        if not self.loopback:
            await self._challenge(hello)
            return
        if self._cookie_rejected:
            await self.close(CLOSE_UNAUTHORIZED, REASON_UNAUTHORIZED)
            return
        if self._cookie_ok:
            await self._enter_ready()
            return
        self._phase = _Phase.AUTH

    async def _on_auth(self, token: str) -> None:
        if not _same(token, self._token):
            await self.close(CLOSE_UNAUTHORIZED, REASON_UNAUTHORIZED)
            return
        await self._enter_ready()

    async def _challenge(self, hello: Hello) -> None:
        """D3: sign a fresh nonce and the dialled origin; the device answers next."""
        origin = hello.origin
        if origin is None or not _origin_allowed(origin, self._allowed_hosts):
            # Every non-loopback session gets a challenge (plan 0055 D4), but the host signs
            # nothing for an origin it does not serve: the signature is random bytes, and the
            # answer, whatever it is, closes with 4001.
            self._origin_refused = True
            self._phase = _Phase.AUTH
            decoy = Challenge(
                t="challenge",
                nonce=handshake.b64u(secrets.token_bytes(handshake.NONCE_BYTES)),
                host=self.hub.identity.host_id,
                host_sig=handshake.b64u(secrets.token_bytes(_SIGNATURE_BYTES)),
            )
            self.enqueue(dump(decoy))
            return
        nonce = handshake.new_nonce()
        if len(nonce) != handshake.NONCE_BYTES or not self.hub.claim_nonce(nonce):
            logger.warning("handshake nonce reused; refusing the session")
            await self.close(CLOSE_UNAUTHORIZED, REASON_UNAUTHORIZED)
            return
        self._claimed_device = hello.device
        self._origin = origin
        self._nonce = nonce
        identity = self.hub.identity
        challenge = Challenge(
            t="challenge",
            nonce=handshake.b64u(nonce),
            host=identity.host_id,
            host_sig=handshake.b64u(identity.sign(handshake.challenge_message(nonce, origin))),
        )
        self._phase = _Phase.AUTH
        self.enqueue(dump(challenge))

    async def _on_device_auth(self, device_sig: str) -> None:
        if self._origin_refused:
            await self.close(CLOSE_UNAUTHORIZED, REASON_UNAUTHORIZED)
            return
        device_id = self._claimed_device
        device = await devices.live_device(device_id) if device_id else None
        if device is None:
            await self.close(CLOSE_UNAUTHORIZED, REASON_UNAUTHORIZED)
            return
        try:
            handshake.verify_auth(
                device.pubkey_ed25519,
                self._nonce,
                self._origin,
                self.hub.identity.host_pubkey_fp,
                device_sig,
            )
        except handshake.BadSignature:
            await self.close(CLOSE_UNAUTHORIZED, REASON_UNAUTHORIZED)
            return
        # Bind before the revocation re-check: a revoke that commits after
        # ``mark_seen`` finds this session in the hub and closes it.
        self.device_id = device_id
        self.hub.bind_device(device_id, self)
        if not await devices.mark_seen(device_id):
            await self.close(CLOSE_UNAUTHORIZED, REASON_UNAUTHORIZED)
            return
        self.scope = device.scope
        await self._enter_ready()

    async def _on_pair_complete(self, frame: PairComplete) -> None:
        """D1: store the device, send ``paired``, close; the device reconnects."""
        if self._origin_refused:
            await self.close(CLOSE_UNAUTHORIZED, REASON_UNAUTHORIZED)
            return
        try:
            paired = await pairing.complete(frame, identity=self.hub.identity)
        except (ProtocolError, ValueError):
            await self.close(CLOSE_UNAUTHORIZED, REASON_UNAUTHORIZED)
            return
        self._phase = _Phase.PAIRED
        self.enqueue(dump(paired))
        while self._pending and not self._closed:
            self._flushed.clear()
            await self._flushed.wait()
        await self.close(1000, _REASON_PAIRED)

    async def _enter_ready(self) -> None:
        if self.loopback:
            self.scope = "owner"
        self._phase = _Phase.READY
        host_seq = await self.hub.host_seq()
        if self._closed:
            # Revoked while authenticating: never attach a closed session.
            return
        await self.hub.attach(self)
        self._attached = True
        welcome = Welcome(
            t="welcome",
            proto=PROTOCOL_VERSION,
            host_seq=host_seq,
            caps=list(HOST_CAPS),
        )
        self.enqueue(dump(welcome))

    async def _on_req(self, req: Req) -> None:
        self._in_request = True
        try:
            res = await dispatch(self, req)
        finally:
            self._in_request = False
            pending = self._deferred
            self._deferred = []
        self.enqueue(dump(res))
        for frame in pending:
            self.enqueue(frame)

    async def _send_loop(self) -> None:
        while True:
            if not self._pending:
                if self._closing:
                    return
                self._wake.clear()
                if not self._pending:
                    await self._wake.wait()
                    continue
            if self._closing:
                return
            text = self._pending[0]
            try:
                await self._connection.send_text(text)
            except ConnectionClosed:
                return
            if self._pending and self._pending[0] == text:
                self._pending.popleft()
            if not self._pending:
                self._flushed.set()

    def _spawn(self, coro: Coroutine[object, object, None]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)

        def _done(done: asyncio.Task[None]) -> None:
            self._tasks.discard(done)
            if done.cancelled():
                return
            exc = done.exception()
            if exc is not None:
                logger.opt(exception=exc).error("session task failed")

        task.add_done_callback(_done)


def _evt_seq(frame: str) -> int | None:
    try:
        parsed: object = json.loads(frame)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    body = cast("dict[str, object]", parsed)
    if body.get("t") != "evt":
        return None
    seq = body.get("s")
    if isinstance(seq, int) and not isinstance(seq, bool):
        return seq
    return None


def _compatible(proto: list[int]) -> bool:
    low, high = proto
    if low > high:
        return False
    return low <= PROTOCOL_VERSION <= high


def _origin_allowed(origin: str, allowed_hosts: frozenset[str]) -> bool:
    """D3: a bare ``ws``/``wss`` origin whose host (and port, if any) is an allowed host.

    The match is exact: no suffix match, and a port must match the entry's port.
    """
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    if parts.scheme not in _ORIGIN_SCHEMES or "@" in parts.netloc or parts.netloc == "":
        return False
    if origin != f"{parts.scheme}://{parts.netloc}":
        return False
    return parts.netloc.lower() in allowed_hosts


def _same(left: str, right: str) -> bool:
    left_b = left.encode()
    right_b = right.encode()
    if len(left_b) != len(right_b):
        return False
    return hmac.compare_digest(left_b, right_b)
