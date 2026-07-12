"""Run coroutines from synchronous CLI entry points.

Module: sevn.cli.asyncio_util
Depends: asyncio, concurrent.futures, typing

Exports:
    run_sync_coro — ``asyncio.run`` when no loop is active; thread offload otherwise.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor


def run_sync_coro[T](coro: Coroutine[object, object, T]) -> T:
    """Run ``coro`` to completion from synchronous CLI code.

    Uses ``asyncio.run`` when no event loop is active. When a loop is already
    running (e.g. IPython, nested tooling), runs ``asyncio.run(coro)`` in a
    worker thread so Typer commands like ``sevn doctor`` do not crash.

    Args:
        coro (Coroutine[object, object, T]): Awaitable to execute.

    Returns:
        T: Coroutine result.

    Examples:
        >>> async def _eg() -> int:
        ...     return 1
        ...
        >>> run_sync_coro(_eg())
        1
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


__all__ = ["run_sync_coro"]
