"""Per-workspace extraction queue (`specs/32-memory-honcho.md` §4.1).

Module: sevn.memory.user_model.queue
Depends: asyncio, collections.abc, typing

Exports:
    UserModelExtractionQueue — serialize extract → merge → save per workspace.
    schedule_user_model_extraction — enqueue one post-reply job.

Examples:
    >>> from sevn.memory.user_model.queue import USER_MODEL_PROMPT_REV
    >>> USER_MODEL_PROMPT_REV
    1
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Final, TypeVar

T = TypeVar("T")

USER_MODEL_PROMPT_REV: Final[int] = 1

_Queues: dict[str, asyncio.Queue[Callable[[], Awaitable[None]] | None]] = {}
_Workers_started: set[str] = set()
_Worker_tasks: set[asyncio.Task[None]] = set()
_Global = asyncio.Lock()


class UserModelExtractionQueue:
    """FIFO queue per workspace — one in-flight extract/merge/save at a time."""

    def __init__(self, workspace_root: str) -> None:
        """Bind a normalized workspace root key.

        Args:
            workspace_root (str): Workspace filesystem root.

        Examples:
            >>> isinstance(UserModelExtractionQueue("."), UserModelExtractionQueue)
            True
        """

        self._key = str(workspace_root)

    async def run_serialized(
        self,
        fn: Callable[[], Awaitable[T]],
    ) -> T:
        """Run ``fn`` after any prior jobs for this workspace complete.

        Args:
            fn (Callable[[], Awaitable[T]]): Async work (extract → merge → save).

        Returns:
            T: Result from ``fn``.

        Examples:
            >>> import asyncio
            >>> q = UserModelExtractionQueue("/tmp/ws")
            >>> asyncio.run(q.run_serialized(lambda: asyncio.sleep(0))) is None
            True
        """

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[T] = loop.create_future()

        async def _job() -> None:
            try:
                result = await fn()
            except Exception as exc:
                if not fut.done():
                    fut.set_exception(exc)
            else:
                if not fut.done():
                    fut.set_result(result)

        await schedule_user_model_extraction(self._key, _job)
        return await fut


async def schedule_user_model_extraction(
    workspace_root: str,
    job: Callable[[], Awaitable[None]],
) -> None:
    """Enqueue post-reply extraction without blocking the caller (`specs/32-memory-honcho.md` §2.7).

    Args:
        workspace_root (str): Workspace filesystem root.
        job (Callable[[], Awaitable[None]]): Extract → merge → persist coroutine.

    Returns:
        None: Always (work continues on the per-workspace worker).

    Examples:
        >>> import asyncio
        >>> async def _noop() -> None:
        ...     return None
        >>> asyncio.run(schedule_user_model_extraction(".", _noop)) is None
        True
    """

    key = str(workspace_root)
    async with _Global:
        q = _Queues.get(key)
        if q is None:
            q = asyncio.Queue()
            _Queues[key] = q
        if key not in _Workers_started:
            _Workers_started.add(key)
            task = asyncio.create_task(_worker(key, q))
            _Worker_tasks.add(task)
            task.add_done_callback(_Worker_tasks.discard)
    await q.put(job)


async def _worker(key: str, q: asyncio.Queue[Callable[[], Awaitable[None]] | None]) -> None:
    """Drain jobs for one workspace until a ``None`` sentinel is queued.

    Args:
        key (str): Workspace key (logging only).
        q (asyncio.Queue): Job queue for this workspace.

    Returns:
        None: Runs until process exit (worker is long-lived).

    Examples:
        >>> import asyncio
        >>> async def _demo() -> None:
        ...     q: asyncio.Queue = asyncio.Queue()
        ...     await q.put(None)
        ...     await _worker("k", q)
        >>> asyncio.run(_demo()) is None
        True
    """

    _ = key
    while True:
        job = await q.get()
        try:
            if job is None:
                return
            await job()
        finally:
            q.task_done()


__all__ = [
    "USER_MODEL_PROMPT_REV",
    "UserModelExtractionQueue",
    "schedule_user_model_extraction",
]
