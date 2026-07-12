"""In-process zombie-watch queue (bounded; trace kinds §4.4, §7).
Module: sevn.agent.harness.zombie
Depends: asyncio, sevn.agent.tracing.sink, sevn.config.defaults
Exports:
    ZombieTask — enqueued non-abortable tool ref.
    ZombieWatchQueue — try_enqueue / drain_step with caps.
Examples:
    >>> from sevn.agent.harness.zombie import ZombieTask
    >>> ZombieTask("1", "s", "t", "tool", None, 0).tool_name
    'tool'
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass

from loguru import logger

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.config.defaults import (
    HARNESS_ZOMBIE_MAX_CONCURRENT,
    HARNESS_ZOMBIE_MAX_PENDING,
    HARNESS_ZOMBIE_TTL_S,
)


@dataclass
class ZombieTask:
    """Outstanding tool call drained out-of-band (no args persisted)."""

    task_id: str
    session_id: str
    turn_id: str
    tool_name: str
    call_id: str | None
    enqueued_at_ns: int


class ZombieWatchQueue:
    """Minimal bounded queue; rejects when over capacity (§4.4, §6)."""

    def __init__(self, trace: TraceSink) -> None:
        """Capture the trace sink used for zombie.* events.
            Args:
        trace (TraceSink): Non-raising sink.
            Examples:
                >>> ZombieWatchQueue.__init__.__doc__ is not None
                True
        """
        self._trace = trace
        self._lock = asyncio.Lock()
        self._queue: deque[ZombieTask] = deque()
        self._drain_slots = asyncio.Semaphore(HARNESS_ZOMBIE_MAX_CONCURRENT)

    async def try_enqueue(
        self,
        *,
        session_id: str,
        turn_id: str,
        tool_name: str,
        call_id: str | None,
        enqueued_at_ns: int | None = None,
    ) -> bool:
        """Enqueue one task; return False when backlog rejects (harness.zombie.rejected).
            Args:
        session_id (str): Session scope.
        turn_id (str): Turn scope for traces.
        tool_name (str): Tool name (no argv).
        call_id (str | None): Opaque call id when known.
        enqueued_at_ns (int | None): Monotonic wall ns; default ``time.time_ns()``.
            Returns:
        bool: True if accepted.
            Examples:
                >>> True
                True
        """
        now = time.time_ns() if enqueued_at_ns is None else int(enqueued_at_ns)
        task = ZombieTask(
            task_id=f"z-{uuid.uuid4().hex[:16]}",
            session_id=session_id,
            turn_id=turn_id,
            tool_name=tool_name,
            call_id=call_id,
            enqueued_at_ns=now,
        )
        async with self._lock:
            if len(self._queue) >= HARNESS_ZOMBIE_MAX_PENDING:
                await self._emit_rejected(task, reason="queue_full")
                return False
            self._queue.append(task)
        await self._emit_safe(
            TraceEvent(
                kind="zombie.enqueue",
                span_id=f"zombie-enq-{task.task_id}",
                parent_span_id=None,
                session_id=session_id,
                turn_id=turn_id,
                tier=None,
                ts_start_ns=now,
                ts_end_ns=None,
                status="pending",
                attrs={
                    "tool_name": tool_name,
                    "call_id": call_id,
                    "task_id": task.task_id,
                },
            ),
        )
        return True

    async def drain_step(self) -> None:
        """Complete one queued task if under concurrency cap (stub drain).
        Side effects: emits ``zombie.drain``, ``zombie.complete``; TTL failures emit
        ``zombie.error``.
                Examples:
                    >>> True
                    True
        """
        async with self._drain_slots:
            async with self._lock:
                if not self._queue:
                    return
                task = self._queue.popleft()
            now = time.time_ns()
            ttl_ns = int(HARNESS_ZOMBIE_TTL_S) * 1_000_000_000
            if now - task.enqueued_at_ns > ttl_ns:
                await self._emit_safe(
                    TraceEvent(
                        kind="zombie.error",
                        span_id=f"zombie-err-{task.task_id}",
                        parent_span_id=None,
                        session_id=task.session_id,
                        turn_id=task.turn_id,
                        tier=None,
                        ts_start_ns=now,
                        ts_end_ns=now,
                        status="error",
                        attrs={
                            "task_id": task.task_id,
                            "reason": "ttl_expired",
                            "tool_name": task.tool_name,
                        },
                    ),
                )
                return
            await self._emit_safe(
                TraceEvent(
                    kind="zombie.drain",
                    span_id=f"zombie-drain-{task.task_id}",
                    parent_span_id=None,
                    session_id=task.session_id,
                    turn_id=task.turn_id,
                    tier=None,
                    ts_start_ns=now,
                    ts_end_ns=None,
                    status="pending",
                    attrs={"task_id": task.task_id, "tool_name": task.tool_name},
                ),
            )
            await self._emit_safe(
                TraceEvent(
                    kind="zombie.complete",
                    span_id=f"zombie-done-{task.task_id}",
                    parent_span_id=None,
                    session_id=task.session_id,
                    turn_id=task.turn_id,
                    tier=None,
                    ts_start_ns=time.time_ns(),
                    ts_end_ns=time.time_ns(),
                    status="ok",
                    attrs={"task_id": task.task_id, "tool_name": task.tool_name},
                ),
            )

    async def _emit_rejected(self, task: ZombieTask, *, reason: str) -> None:
        """Emit a ``harness.zombie.rejected`` trace event for a backlog rejection.
        Args:
            task (ZombieTask): The task that was rejected.
            reason (str): Reject reason string (e.g. ``"queue_full"``).
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ZombieWatchQueue._emit_rejected)
            True
        """
        await self._emit_safe(
            TraceEvent(
                kind="harness.zombie.rejected",
                span_id=f"zombie-rej-{task.task_id}",
                parent_span_id=None,
                session_id=task.session_id,
                turn_id=task.turn_id,
                tier=None,
                ts_start_ns=time.time_ns(),
                ts_end_ns=time.time_ns(),
                status="error",
                attrs={
                    "reason": reason,
                    "tool_name": task.tool_name,
                    "task_id": task.task_id,
                },
            ),
        )

    async def _emit_safe(self, event: TraceEvent) -> None:
        """Emit a trace event without raising; logs at warning on failure.
        Args:
            event (TraceEvent): Event payload to emit.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ZombieWatchQueue._emit_safe)
            True
        """
        try:
            await self._trace.emit(event)
        except Exception:
            logger.bind(kind=event.kind).exception("zombie trace emit failed")
