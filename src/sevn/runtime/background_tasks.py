"""Fire-and-forget asyncio tasks with exception logging and strong references.

Module: sevn.runtime.background_tasks
Depends: asyncio, collections.abc, loguru, typing

Exports:
    spawn_logged — schedule a coroutine; log unhandled exceptions on completion.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

_HOLDERS: set[asyncio.Task[Any]] = set()


def spawn_logged(
    coro: Coroutine[Any, Any, Any],
    *,
    label: str,
    on_error: Callable[[str], None] | None = None,
    name: str | None = None,
) -> asyncio.Task[Any] | None:
    """Schedule ``coro`` and log exceptions when the task completes.

    Args:
        coro (Coroutine[Any, Any, Any]): Awaitable to run in the background.
        label (str): Stable event label for logs and optional ``on_error`` spy.
        on_error (Callable[[str], None] | None, optional): Called with ``label``
            when the task finishes with an exception (not when cancelled).
        name (str | None, optional): Forwarded to :func:`asyncio.create_task`.

    Returns:
        asyncio.Task[Any] | None: Created task, or ``None`` when no loop is running.

    Examples:
        >>> async def _noop() -> None:
        ...     return None
        >>> spawn_logged(_noop(), label="demo") is None
        True
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        return None

    task = loop.create_task(coro) if name is None else loop.create_task(coro, name=name)
    _HOLDERS.add(task)

    def _done(t: asyncio.Task[Any]) -> None:
        _HOLDERS.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is None:
            return
        if on_error is not None:
            on_error(label)
            return
        logger.opt(exception=exc).error("background_task_failed label={}", label)

    task.add_done_callback(_done)
    return task
