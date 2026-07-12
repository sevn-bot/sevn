"""Debounced fire-and-forget trajectory ingest queue.

Module: sevn.self_improve.trajectories.queue
Depends: asyncio, collections.abc, typing

Exports:
    schedule_trajectory_ingest — enqueue one post-turn ingest job.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

_INGEST_DEBOUNCE_S: Final[float] = 0.5

_Queues: dict[str, asyncio.Queue[Callable[[], Awaitable[None]] | None]] = {}
_Workers_started: set[str] = set()
_Worker_tasks: set[asyncio.Task[None]] = set()
_Pending_turns: dict[str, set[str]] = {}
_Global = asyncio.Lock()


async def schedule_trajectory_ingest(
    workspace_key: str,
    turn_id: str,
    job: Callable[[], Awaitable[None]],
) -> None:
    """Enqueue post-turn ingest without blocking the caller.

    Duplicate ``turn_id`` schedules within :data:`_INGEST_DEBOUNCE_S` are
    coalesced so rapid span flushes produce one ingest pass.

    Args:
        workspace_key (str): Stable workspace identifier.
        turn_id (str): Gateway correlation id for the finished turn.
        job (Callable[[], Awaitable[None]]): Ingest coroutine.

    Returns:
        None: Always (work continues on the per-workspace worker).

    Examples:
        >>> import asyncio
        >>> async def _noop() -> None:
        ...     return None
        >>> asyncio.run(schedule_trajectory_ingest("ws", "turn-1", _noop)) is None
        True
    """
    key = str(workspace_key)
    async with _Global:
        pending = _Pending_turns.setdefault(key, set())
        if turn_id in pending:
            return
        pending.add(turn_id)
        q = _Queues.get(key)
        if q is None:
            q = asyncio.Queue()
            _Queues[key] = q
        if key not in _Workers_started:
            _Workers_started.add(key)
            task = asyncio.create_task(_worker(key, q))
            _Worker_tasks.add(task)
            task.add_done_callback(_Worker_tasks.discard)

        async def _debounced_job() -> None:
            try:
                await asyncio.sleep(_INGEST_DEBOUNCE_S)
                await job()
            finally:
                async with _Global:
                    bucket = _Pending_turns.get(key)
                    if bucket is not None:
                        bucket.discard(turn_id)
                        if not bucket:
                            _Pending_turns.pop(key, None)

        await q.put(_debounced_job)


async def _worker(key: str, q: asyncio.Queue[Callable[[], Awaitable[None]] | None]) -> None:
    """Drain ingest jobs for one workspace until a ``None`` sentinel is queued.

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


__all__ = ["schedule_trajectory_ingest"]
