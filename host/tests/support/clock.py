"""Injectable clock the protocol tests pass into Hub."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any


class ManualClock:
    """Monotonic clock with explicit `advance`.

    The coalescer must call `time()` and `call_later(delay, callback)`.
    `advance` runs due callbacks. Awaitable callbacks are scheduled on the
    running loop.
    """

    def __init__(self) -> None:
        self.now = 0.0
        self._pending: list[tuple[float, Callable[[], Any]]] = []

    def time(self) -> float:
        return self.now

    def call_later(self, delay: float, callback: Callable[[], Any]) -> None:
        self._pending.append((self.now + delay, callback))

    def advance(self, seconds: float) -> None:
        self.now += seconds
        due = [callback for when, callback in self._pending if when <= self.now]
        self._pending = [(when, callback) for when, callback in self._pending if when > self.now]
        for callback in due:
            result = callback()
            if inspect.isawaitable(result):
                asyncio.get_running_loop().create_task(result)
