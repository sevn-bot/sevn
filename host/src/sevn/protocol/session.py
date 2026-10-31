"""Handshake and per-session outbound queue (D5-D7, D12)."""

from __future__ import annotations

import asyncio
import enum
import hmac
import json
from collections import deque
from collections.abc import Coroutine
from contextlib import suppress
from typing import Self, cast

from sevn.contracts.errors import ProtocolError
from sevn.contracts.frames import (
    AuthDevice,
    AuthToken,
    FrameError,
    Hello,
    Req,
    Welcome,
    dump,
    parse,
)
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


class _Phase(enum.Enum):
    HELLO = "hello"
    AUTH = "auth"
    READY = "ready"


class Session:
    """One protocol session on top of a ``Connection``."""

    scope: Scope
    hub: Hub

    def __init__(
        self,
        connection: Connection,
        hub: Hub,
        *,
        token: str,
        queue_limit: int,
        cookie: str | None = None,
    ) -> None:
        self._connection = connection
        self.hub = hub
        self.scope = "read_only"
        self._token = token
        self._queue_limit = queue_limit
        self._phase = _Phase.HELLO
        self._cookie_ok = False
        self._cookie_rejected = False
        if cookie is not None:
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

    @classmethod
    def for_test(cls, *, scope: Scope) -> Self:
        session = cls.__new__(cls)
        session.scope = scope
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
        attached = self._attached
        self._attached = False
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
        if isinstance(frame, Hello) and self._phase is _Phase.HELLO:
            await self._on_hello(frame)
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

    async def _enter_ready(self) -> None:
        self.scope = "owner"
        self._phase = _Phase.READY
        host_seq = await self.hub.host_seq()
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


def _same(left: str, right: str) -> bool:
    left_b = left.encode()
    right_b = right.encode()
    if len(left_b) != len(right_b):
        return False
    return hmac.compare_digest(left_b, right_b)
