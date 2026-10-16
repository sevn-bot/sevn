"""Coalesce ephemeral ticks over a 50 ms window (D12)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Protocol

from sevn.contracts.errors import JsonValue

COALESCE_WINDOW_SECONDS = 0.05

type TickPayload = dict[str, JsonValue]
type Flush = Callable[[str, TickPayload], None]


class Clock(Protocol):
    """Injectable monotonic clock. ``ManualClock`` in tests implements this."""

    def time(self) -> float: ...

    def call_later(self, delay: float, callback: Callable[[], object]) -> None: ...


class TickCoalescer:
    """Merge ``(kind, key)`` updates until the window elapses.

    The ``text`` field concatenates. Every other field keeps the latest value.
    """

    def __init__(self, on_flush: Flush, clock: Clock | None = None) -> None:
        self._on_flush = on_flush
        self._clock = clock
        self._buckets: dict[tuple[str, str], TickPayload] = {}
        self._armed: set[tuple[str, str]] = set()

    def add(self, kind: str, key: str, data: Mapping[str, JsonValue]) -> None:
        slot = (kind, key)
        current = self._buckets.get(slot)
        if current is None:
            self._buckets[slot] = dict(data)
            self._arm(slot)
            return
        self._buckets[slot] = _merge(current, data)

    def _arm(self, slot: tuple[str, str]) -> None:
        if slot in self._armed:
            return
        self._armed.add(slot)
        now = self._now()
        delay = (now + COALESCE_WINDOW_SECONDS) - now
        self._schedule(delay, lambda slot=slot: self._fire(slot))

    def _fire(self, slot: tuple[str, str]) -> None:
        self._armed.discard(slot)
        payload = self._buckets.pop(slot, None)
        if payload is None:
            return
        self._on_flush(slot[0], payload)

    def _now(self) -> float:
        if self._clock is not None:
            return self._clock.time()
        return asyncio.get_running_loop().time()

    def _schedule(self, delay: float, callback: Callable[[], None]) -> None:
        if self._clock is not None:
            self._clock.call_later(delay, callback)
            return
        asyncio.get_running_loop().call_later(delay, callback)


def _merge(existing: TickPayload, update: Mapping[str, JsonValue]) -> TickPayload:
    merged = dict(existing)
    for key, value in update.items():
        if key == "text" and isinstance(value, str):
            previous = merged.get(key)
            merged[key] = previous + value if isinstance(previous, str) else value
            continue
        merged[key] = value
    return merged
