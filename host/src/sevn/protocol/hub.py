"""Durable fan-out, tick coalescing, and sync.since replay (D10, D12)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from typing import Protocol, cast

from sevn.config import Settings
from sevn.contracts.errors import JsonObject, JsonValue
from sevn.contracts.frames import Evt, Tick, dump
from sevn.identity import HostIdentity, load_or_create
from sevn.log import logger
from sevn.paths import Paths
from sevn.protocol.ticks import Clock, TickCoalescer
from sevn.secrets.backends import open_backend
from sevn.store.models import Event
from sevn.store.oplog import OpLog
from sevn.store.outbox import Outbox, ResyncRequired

type OpWork = Callable[[], Awaitable[Mapping[str, object]]]


class Peer(Protocol):
    def deliver(self, frame: str) -> None: ...


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
        self._op_lock = asyncio.Lock()
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
        event = await self.outbox.append(type, entity, payload)
        await self._fanout(_event_frame(event))
        return event

    async def relay(self, event: Event) -> None:
        """Fan out an event that was already committed with the turn."""
        await self._fanout(_event_frame(event))

    def tick(self, kind: str, key: str, data: Mapping[str, object]) -> None:
        self._ticks.add(kind, key, _as_json_object(data))

    async def sync_since(self, peer: Peer, seq: int) -> int:
        rows = await self.outbox.since(seq)
        for row in rows:
            peer.deliver(_event_frame(row))
        if not rows:
            return seq
        return rows[-1].seq

    async def host_seq(self) -> int:
        try:
            rows = await self.outbox.since(0)
        except ResyncRequired as exc:
            rows = await self.outbox.since(exc.min_seq - 1)
        if not rows:
            return 0
        return rows[-1].seq

    async def claim_op(
        self,
        op_id: str,
        method: str,
        work: OpWork,
    ) -> dict[str, object]:
        """Run ``work`` once per ``op_id`` and replay the stored result after that."""
        async with self._op_lock:
            found = await self.oplog.lookup(op_id)
            if found is not None:
                return dict(found.result)
            result = dict(await work())
            await self.oplog.record(op_id, method, result)
            return result

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
