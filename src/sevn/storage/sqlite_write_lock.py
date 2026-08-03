"""Asyncio write serialization for shared ``sevn.db`` connections.

Module: sevn.storage.sqlite_write_lock

The gateway holds one SQLite connection on ``app.state.sqlite_conn`` with
``check_same_thread=False``. Concurrent asyncio tasks must not interleave
writes without coordination — this module exposes a process-wide
:class:`asyncio.Lock` for that single-writer pattern.

Exports:
    sqlite_write_lock — lazy singleton lock for gateway / CLI async callers.
    run_sqlite_write — run a sync write callable under the lock.

Examples:
    >>> import asyncio
    >>> from sevn.storage.sqlite_write_lock import sqlite_write_lock
    >>> isinstance(sqlite_write_lock(), asyncio.Lock)
    True
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

_T = TypeVar("_T")

_write_lock: asyncio.Lock | None = None


def sqlite_write_lock() -> asyncio.Lock:
    """Return the process-wide SQLite write lock, creating it lazily.

    Returns:
        asyncio.Lock: Shared lock for serializing ``sevn.db`` writes.

    Examples:
        >>> lock = sqlite_write_lock()
        >>> lock is sqlite_write_lock()
        True
    """
    global _write_lock
    if _write_lock is None:
        _write_lock = asyncio.Lock()
    return _write_lock


async def run_sqlite_write[T](fn: Callable[[], T]) -> T:
    """Run ``fn`` on a worker thread while holding :func:`sqlite_write_lock`.

    Args:
        fn (Callable[[], T]): Synchronous SQLite write body.

    Returns:
        T: Result from ``fn``.

    Examples:
        >>> import asyncio
        >>> async def _eg() -> int:
        ...     return await run_sqlite_write(lambda: 1)
        ...
        >>> asyncio.run(_eg())
        1
    """
    async with sqlite_write_lock():
        return await asyncio.to_thread(fn)


__all__ = ["run_sqlite_write", "sqlite_write_lock"]
