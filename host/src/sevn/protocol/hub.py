"""Durable fan-out, tick coalescing, and sync.since replay (D10, D12)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Protocol, cast

from sevn.config import Settings
from sevn.contracts.errors import JsonObject, JsonValue, ProtocolError
from sevn.contracts.frames import Evt, Tick, dump
from sevn.identity import HostIdentity, load_or_create
from sevn.log import logger
from sevn.paths import Paths
from sevn.protocol.ticks import Clock, TickCoalescer
from sevn.secrets.backends import open_backend
from sevn.store.models import Event
from sevn.store.oplog import OpLog
from sevn.store.outbox import Outbox

type OpWork = Callable[[], Awaitable[Mapping[str, object]]]

_OP_SEP = "\x1f"
_active_op: ContextVar[tuple[str, str] | None] = ContextVar("sevn_active_op", default=None)


class Peer(Protocol):
    def deliver(self, frame: str) -> None: ...

    def hold_live(self) -> None: ...

    def replay(self, frame: str) -> None: ...

    def release_live(self, high_water: int) -> None: ...


@dataclass(frozen=True, slots=True)
class SyncPage:
    host_seq: int
    next_seq: int
    more: bool


class Hub:
    """Appends durable events and fans frames out to ready sessions.

    The peer set lock is never held across a send. Sessions enqueue without
    waiting for the client to read.
    """

    def __init__(self, outbox: Outbox, oplog: OpLog, *, clock: Clock | None = None) -> None:
        self.outbox = outbox
        self.oplog = oplog
        self.identity = _load_identity()
        self._lock = asyncio.Lock()
        self._op_locks: dict[str, asyncio.Lock] = {}
        self._peers: dict[int, Peer] = {}
        self._background: set[asyncio.Task[None]] = set()
        self._ticks = TickCoalescer(self._on_tick, clock)

    async def attach(self, peer: Peer) -> None:
        async with self._lock:
            self._peers[id(peer)] = peer

    async def detach(self, peer: Peer) -> None:
        async with self._lock:
            self._peers.pop(id(peer), None)

    async def emit(self, type: str, entity: str, payload: Mapping[str, object]) -> Event:
        event = await self.outbox.append(type, entity, payload, op=_active_op.get())
        await self._fanout(_event_frame(event))
        return event

    async def relay(self, event: Event) -> None:
        """Fan out an event that was already committed with the turn."""
        await self._fanout(_event_frame(event))

    def tick(self, kind: str, key: str, data: Mapping[str, object]) -> None:
        self._ticks.add(kind, key, _as_json_object(data))

    async def sync_since(self, peer: Peer, seq: int, *, limit: int) -> SyncPage:
        """Replay one page. Live frames at or below the page stay out of the mix."""
        peer.hold_live()
        high = seq
        try:
            head = await self.outbox.head()
            high = head
            if seq > head:
                return SyncPage(host_seq=head, next_seq=head, more=False)
            rows = await self.outbox.since(seq, limit=limit + 1)
            more = len(rows) > limit
            page = rows[:limit]
            for row in page:
                peer.replay(_event_frame(row))
            if page:
                high = page[-1].seq
            next_seq = head if not more else high
            return SyncPage(host_seq=head, next_seq=next_seq, more=more)
        finally:
            peer.release_live(high)

    async def host_seq(self) -> int:
        return await self.outbox.head()

    async def claim_op(
        self,
        op_id: str,
        method: str,
        params_hash: str,
        work: OpWork,
    ) -> dict[str, object]:
        """Run ``work`` once per ``op_id`` and replay the stored result after that."""
        stored_method = f"{method}{_OP_SEP}{params_hash}"
        async with self._lock_for(op_id):
            found = await self.oplog.lookup(op_id)
            if found is not None:
                _require_same_op(found.method, stored_method)
                if found.result.get("_pending") is True:
                    raise ProtocolError("op_in_progress", "op is still running")
                return dict(found.result)
            token = _active_op.set((op_id, stored_method))
            try:
                result = dict(await work())
            finally:
                _active_op.reset(token)
            saved = await self.oplog.lookup(op_id)
            if saved is None:
                await self.oplog.record(op_id, stored_method, result)
            else:
                await self.oplog.replace_result(op_id, result)
            return result

    def _lock_for(self, op_id: str) -> asyncio.Lock:
        lock = self._op_locks.get(op_id)
        if lock is None:
            lock = asyncio.Lock()
            self._op_locks[op_id] = lock
        return lock

    async def _fanout(self, frame: str) -> None:
        async with self._lock:
            peers = tuple(self._peers.values())
        for peer in peers:
            peer.deliver(frame)

    def _on_tick(self, kind: str, data: dict[str, JsonValue]) -> None:
        frame = dump(Tick(t="tick", k=kind, d=data))
        self._later(self._fanout(frame))

    def _later(self, coro: Coroutine[object, object, None]) -> None:
        task = asyncio.create_task(coro)
        self._background.add(task)

        def _done(done: asyncio.Task[None]) -> None:
            self._background.discard(done)
            if done.cancelled():
                return
            exc = done.exception()
            if exc is not None:
                logger.opt(exception=exc).error("hub task failed")

        task.add_done_callback(_done)


def _require_same_op(stored: str, expected: str) -> None:
    stored_method, _, stored_hash = stored.partition(_OP_SEP)
    expected_method, _, expected_hash = expected.partition(_OP_SEP)
    if stored_method != expected_method or (stored_hash != "" and stored_hash != expected_hash):
        raise ProtocolError("op_mismatch", "op_id does not match the original call")


def _load_identity() -> HostIdentity:
    return load_or_create(open_backend(Settings.load(), Paths.from_env()))


def _event_frame(event: Event) -> str:
    return dump(Evt(t="evt", s=event.seq, k=event.type, d=_as_json_object(event.payload)))


def _as_json_object(data: Mapping[str, object]) -> JsonObject:
    body: dict[str, JsonValue] = {}
    for key, value in data.items():
        body[key] = _json_value(value)
    return body


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        raw = cast("Mapping[object, object]", value)
        nested: dict[str, JsonValue] = {}
        for key, item in raw.items():
            nested[str(key)] = _json_value(item)
        return nested
    if isinstance(value, list):
        items = cast("list[object]", value)
        return [_json_value(item) for item in items]
    raise TypeError("event payload is not JSON")
