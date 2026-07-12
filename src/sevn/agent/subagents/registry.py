"""Async-safe in-memory registry of tracked sub-agent runs (D3).

Module: sevn.agent.subagents.registry
Depends: asyncio, dataclasses, time, loguru, sevn.agent.subagents.models

Also exports the ``PersistHook`` and ``TraceHook`` type aliases — injectable
async write-through callbacks (D10 persistence, W5 tracing).

Exports:
    RegistrySnapshot — read-only, lock-consistent view used for atomic limit checks.
    SubAgentRegistry — the authoritative ``{id -> SubAgentRun}`` map.

Examples:
    >>> import asyncio
    >>> async def _demo() -> str:
    ...     registry = SubAgentRegistry()
    ...     run = await registry.register(
    ...         level=1, role="tier_b", specialist=None, parent_id=None,
    ...         session_id="s1", channel="telegram", task_summary="hi",
    ...     )
    ...     return run.status.value
    >>> asyncio.run(_demo())
    'pending'
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from loguru import logger

from sevn.agent.subagents.models import (
    ACTIVE_STATUSES,
    SubAgentRun,
    SubAgentStatus,
    generate_short_id,
)

if TYPE_CHECKING:
    from sevn.config.sections.subagents import Role

__all__ = ["PersistHook", "RegistrySnapshot", "SubAgentRegistry", "TraceHook"]

PersistHook = Callable[[SubAgentRun], Awaitable[None]]
"""Write-through persistence callback invoked after every registry transition.

Injected by the caller (typically the supervisor, backed by
``sevn.agent.subagents.storage`` when a DB connection is available) so unit
tests can run the registry with no persistence hook at all (D10).
"""

TraceHook = Callable[[SubAgentRun, str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    """Read-only view of all runs, captured under the registry lock.

    Used by :meth:`SubAgentRegistry.register_if` so a caller (the supervisor)
    can check concurrency limits and register atomically — without this,
    two concurrent ``spawn()`` calls could both observe a count under the cap
    and both register, breaking the limit.
    """

    _runs: tuple[SubAgentRun, ...]

    def counts(self) -> dict[tuple[int, str], int]:
        """Active-run counts grouped by ``(level, role)`` (D3 ``counts()``).

        Returns:
            dict[tuple[int, str], int]: Active-run count keyed by ``(level, role)``.

        Examples:
            >>> snap = RegistrySnapshot(())
            >>> snap.counts()
            {}
        """
        out: dict[tuple[int, str], int] = {}
        for run in self._runs:
            if run.status in ACTIVE_STATUSES:
                key = (run.level, run.role)
                out[key] = out.get(key, 0) + 1
        return out

    def active_children(self, parent_id: str) -> int:
        """Count active (pending/running) level-2 children of ``parent_id``.

        Args:
            parent_id (str): Level-1 run id whose active children are counted.

        Returns:
            int: Number of active (pending/running) level-2 children.

        Examples:
            >>> RegistrySnapshot(()).active_children("a1f3")
            0
        """
        return sum(
            1 for run in self._runs if run.parent_id == parent_id and run.status in ACTIVE_STATUSES
        )

    def active_specialist(self, name: str) -> int:
        """Count active runs bound to specialist ``name`` (D8 ``max_concurrent``).

        Args:
            name (str): Specialist id to count active runs for.

        Returns:
            int: Number of active runs bound to that specialist.

        Examples:
            >>> RegistrySnapshot(()).active_specialist("media_generator")
            0
        """
        return sum(
            1 for run in self._runs if run.specialist == name and run.status in ACTIVE_STATUSES
        )


async def _trace_safe(hook: TraceHook | None, run: SubAgentRun, phase: str) -> None:
    """Invoke the tracing hook, swallowing and logging any failure.

    Args:
        hook (TraceHook | None): Injected lifecycle callback, or ``None``.
        run (SubAgentRun): Row to describe in telemetry/OTel.
        phase (str): Lifecycle phase that triggered the hook.

    Examples:
        >>> import asyncio
        >>> asyncio.run(_trace_safe(None, None, "registered"))  # doctest: +SKIP
    """
    if hook is None:
        return
    try:
        await hook(run, phase)
    except Exception:
        logger.bind(subagent_id=run.id, phase=phase).exception(
            "subagent registry trace hook failed"
        )


async def _persist_safe(hook: PersistHook | None, run: SubAgentRun) -> None:
    """Invoke the persistence hook, swallowing and logging any failure.

    Args:
        hook (PersistHook | None): Injected write-through callback, or ``None``.
        run (SubAgentRun): Row to persist.

    Examples:
        >>> import asyncio
        >>> asyncio.run(_persist_safe(None, None))  # doctest: +SKIP
    """
    if hook is None:
        return
    try:
        await hook(run)
    except Exception:
        logger.bind(subagent_id=run.id).exception("subagent registry persist hook failed")


class SubAgentRegistry:
    """Authoritative in-memory ``{id -> SubAgentRun}`` map (D3).

    Async-safe via a single internal :class:`asyncio.Lock` guarding all
    mutations; reads that need a consistent multi-field view (limit checks)
    go through :meth:`register_if`, which holds the lock across the whole
    check-then-register critical section.

    Args:
        persist (PersistHook | None): Optional write-through persistence
            callback invoked (best-effort) after every transition.
        trace (TraceHook | None): Optional tracing callback (W5) after register
            and every transition.

    Examples:
        >>> registry = SubAgentRegistry()
        >>> isinstance(registry, SubAgentRegistry)
        True
    """

    def __init__(
        self,
        *,
        persist: PersistHook | None = None,
        trace: TraceHook | None = None,
    ) -> None:
        """Build an empty registry with optional persistence and tracing hooks.

        Args:
            persist (PersistHook | None): Optional callback invoked (best-effort)
                after every transition; ``None`` disables persistence (D10).
            trace (TraceHook | None): Optional tracing callback (W5); ``None``
                disables sub-agent OTel/mission telemetry emission.

        Examples:
            >>> isinstance(SubAgentRegistry(), SubAgentRegistry)
            True
        """
        self._lock = asyncio.Lock()
        self._runs: dict[str, SubAgentRun] = {}
        self._persist = persist
        self._trace = trace

    def wire_trace(self, hook: TraceHook) -> None:
        """Attach or replace the tracing hook after construction (gateway boot).

        Args:
            hook (TraceHook): Lifecycle callback (W5).

        Examples:
            >>> from sevn.agent.subagents.registry import SubAgentRegistry
            >>> from sevn.agent.tracing.subagent_trace import build_subagent_trace_hook
            >>> reg = SubAgentRegistry()
            >>> reg.wire_trace(build_subagent_trace_hook(reg))
            >>> reg._trace is not None
            True
        """
        self._trace = hook

    def _snapshot_locked(self) -> RegistrySnapshot:
        """Capture a :class:`RegistrySnapshot` of current runs (caller holds the lock).

        Returns:
            RegistrySnapshot: Immutable view of all runs at capture time.

        Examples:
            >>> isinstance(SubAgentRegistry()._snapshot_locked(), RegistrySnapshot)
            True
        """
        return RegistrySnapshot(tuple(self._runs.values()))

    def _register_locked(
        self,
        *,
        level: Literal[1, 2],
        role: Role,
        specialist: str | None,
        parent_id: str | None,
        session_id: str,
        channel: str,
        task_summary: str,
        trace_id: str | None,
        now_ns: int | None,
    ) -> SubAgentRun:
        """Insert a new ``pending`` run into the map (caller holds the lock).

        Args:
            level (Literal[1, 2]): Sub-agent level.
            role (Role): Owning level-1 role.
            specialist (str | None): Specialist id for a specialist level-2 run.
            parent_id (str | None): Spawning level-1 run id (level-2 only).
            session_id (str): Gateway session id.
            channel (str): Channel name.
            task_summary (str): Short task description.
            trace_id (str | None): OTel span id, if already known.
            now_ns (int | None): Test clock override for ``started_at``.

        Returns:
            SubAgentRun: The newly inserted ``pending`` row.

        Examples:
            >>> run = SubAgentRegistry()._register_locked(
            ...     level=1, role="tier_b", specialist=None, parent_id=None,
            ...     session_id="s", channel="c", task_summary="t", trace_id=None,
            ...     now_ns=1,
            ... )
            >>> run.status.value
            'pending'
        """
        subagent_id = generate_short_id(self._runs)
        started_at = now_ns if now_ns is not None else time.time_ns()
        effective_trace_id = trace_id if trace_id is not None else f"sub-{subagent_id}"
        run = SubAgentRun(
            id=subagent_id,
            level=level,
            role=role,
            specialist=specialist,
            parent_id=parent_id,
            session_id=session_id,
            channel=channel,
            task_summary=task_summary,
            status=SubAgentStatus.PENDING,
            started_at=started_at,
            finished_at=None,
            trace_id=effective_trace_id,
        )
        self._runs[subagent_id] = run
        return run

    async def register(
        self,
        *,
        level: Literal[1, 2],
        role: Role,
        specialist: str | None = None,
        parent_id: str | None = None,
        session_id: str,
        channel: str,
        task_summary: str,
        trace_id: str | None = None,
        now_ns: int | None = None,
    ) -> SubAgentRun:
        """Register a new run unconditionally and return it (``pending``).

        Args:
            level (Literal[1, 2]): Sub-agent level.
            role (Role): Owning level-1 role.
            specialist (str | None): Specialist id for a specialist level-2 run.
            parent_id (str | None): Spawning level-1 run id (level-2 only).
            session_id (str): Gateway session id.
            channel (str): Channel name.
            task_summary (str): Short task description.
            trace_id (str | None): OTel span id, if already known.
            now_ns (int | None): Test clock override.

        Returns:
            SubAgentRun: The newly registered ``pending`` row.

        Examples:
            >>> import asyncio
            >>> async def _demo() -> int:
            ...     registry = SubAgentRegistry()
            ...     run = await registry.register(
            ...         level=1, role="tier_b", session_id="s", channel="c",
            ...         task_summary="t",
            ...     )
            ...     return len(run.id)
            >>> asyncio.run(_demo())
            4
        """
        async with self._lock:
            run = self._register_locked(
                level=level,
                role=role,
                specialist=specialist,
                parent_id=parent_id,
                session_id=session_id,
                channel=channel,
                task_summary=task_summary,
                trace_id=trace_id,
                now_ns=now_ns,
            )
        await _persist_safe(self._persist, run)
        await _trace_safe(self._trace, run, "registered")
        return run

    async def register_if(
        self,
        predicate: Callable[[RegistrySnapshot], bool],
        *,
        level: Literal[1, 2],
        role: Role,
        specialist: str | None = None,
        parent_id: str | None = None,
        session_id: str,
        channel: str,
        task_summary: str,
        trace_id: str | None = None,
        now_ns: int | None = None,
    ) -> SubAgentRun | None:
        """Atomically check ``predicate(snapshot)`` and register iff it passes.

        Holds the internal lock across the whole check-then-register
        critical section so concurrent spawns cannot both observe a count
        under a cap and both register (D5 concurrency-safe limit enforcement).

        Args:
            predicate (Callable[[RegistrySnapshot], bool]): Evaluated against a
                lock-consistent snapshot; registration proceeds only if ``True``.
            level (Literal[1, 2]): Sub-agent level.
            role (Role): Owning level-1 role.
            specialist (str | None): Specialist id for a specialist level-2 run.
            parent_id (str | None): Spawning level-1 run id (level-2 only).
            session_id (str): Gateway session id.
            channel (str): Channel name.
            task_summary (str): Short task description.
            trace_id (str | None): OTel span id, if already known.
            now_ns (int | None): Test clock override.

        Returns:
            SubAgentRun | None: The registered row, or ``None`` when the
            predicate rejected the snapshot (caller maps this to
            ``SubAgentLimitExceeded``).

        Examples:
            >>> import asyncio
            >>> async def _demo() -> tuple[bool, bool]:
            ...     registry = SubAgentRegistry()
            ...     ok = await registry.register_if(
            ...         lambda snap: snap.counts().get((1, "tier_b"), 0) < 1,
            ...         level=1, role="tier_b", session_id="s", channel="c",
            ...         task_summary="t",
            ...     )
            ...     blocked = await registry.register_if(
            ...         lambda snap: snap.counts().get((1, "tier_b"), 0) < 1,
            ...         level=1, role="tier_b", session_id="s", channel="c",
            ...         task_summary="t",
            ...     )
            ...     return (ok is not None, blocked is None)
            >>> asyncio.run(_demo())
            (True, True)
        """
        async with self._lock:
            if not predicate(self._snapshot_locked()):
                return None
            run = self._register_locked(
                level=level,
                role=role,
                specialist=specialist,
                parent_id=parent_id,
                session_id=session_id,
                channel=channel,
                task_summary=task_summary,
                trace_id=trace_id,
                now_ns=now_ns,
            )
        await _persist_safe(self._persist, run)
        await _trace_safe(self._trace, run, "registered")
        return run

    async def _transition(
        self,
        subagent_id: str,
        status: SubAgentStatus,
        *,
        finished: bool,
        now_ns: int | None,
    ) -> SubAgentRun:
        """Set one run's status (and ``finished_at`` when terminal), then persist.

        Args:
            subagent_id (str): Target run id.
            status (SubAgentStatus): New status to record.
            finished (bool): When ``True``, stamp ``finished_at`` (terminal states).
            now_ns (int | None): Test clock override for ``finished_at``.

        Returns:
            SubAgentRun: The updated row.

        Raises:
            KeyError: When ``subagent_id`` is not registered.

        Examples:
            >>> import asyncio
            >>> async def _demo() -> str:
            ...     registry = SubAgentRegistry()
            ...     run = await registry.register(
            ...         level=1, role="tier_b", session_id="s", channel="c",
            ...         task_summary="t",
            ...     )
            ...     updated = await registry._transition(
            ...         run.id, SubAgentStatus.RUNNING, finished=False, now_ns=None,
            ...     )
            ...     return updated.status.value
            >>> asyncio.run(_demo())
            'running'
        """
        async with self._lock:
            run = self._runs.get(subagent_id)
            if run is None:
                msg = f"unknown sub-agent id: {subagent_id!r}"
                raise KeyError(msg)
            finished_at = run.finished_at
            if finished:
                finished_at = now_ns if now_ns is not None else time.time_ns()
            updated = replace(run, status=status, finished_at=finished_at)
            self._runs[subagent_id] = updated
        await _persist_safe(self._persist, updated)
        await _trace_safe(self._trace, updated, status.value)
        return updated

    async def mark_running(self, subagent_id: str) -> SubAgentRun:
        """Transition a ``pending`` row to ``running``.

        Args:
            subagent_id (str): Target run id.

        Returns:
            SubAgentRun: The updated ``running`` row.

        Examples:
            >>> import asyncio
            >>> async def _demo() -> str:
            ...     registry = SubAgentRegistry()
            ...     run = await registry.register(
            ...         level=1, role="tier_b", session_id="s", channel="c", task_summary="t",
            ...     )
            ...     updated = await registry.mark_running(run.id)
            ...     return updated.status.value
            >>> asyncio.run(_demo())
            'running'
        """
        return await self._transition(
            subagent_id, SubAgentStatus.RUNNING, finished=False, now_ns=None
        )

    async def mark_done(self, subagent_id: str, *, now_ns: int | None = None) -> SubAgentRun:
        """Transition a row to ``done`` (terminal, success).

        Args:
            subagent_id (str): Target run id.
            now_ns (int | None): Test clock override for ``finished_at``.

        Returns:
            SubAgentRun: The updated ``done`` row.

        Examples:
            >>> import asyncio
            >>> async def _demo() -> str:
            ...     registry = SubAgentRegistry()
            ...     run = await registry.register(
            ...         level=1, role="tier_b", session_id="s", channel="c", task_summary="t",
            ...     )
            ...     updated = await registry.mark_done(run.id)
            ...     return updated.status.value
            >>> asyncio.run(_demo())
            'done'
        """
        return await self._transition(
            subagent_id, SubAgentStatus.DONE, finished=True, now_ns=now_ns
        )

    async def mark_failed(self, subagent_id: str, *, now_ns: int | None = None) -> SubAgentRun:
        """Transition a row to ``failed`` (terminal — exception or timeout).

        Args:
            subagent_id (str): Target run id.
            now_ns (int | None): Test clock override for ``finished_at``.

        Returns:
            SubAgentRun: The updated ``failed`` row.

        Examples:
            >>> import asyncio
            >>> async def _demo() -> str:
            ...     registry = SubAgentRegistry()
            ...     run = await registry.register(
            ...         level=1, role="tier_b", session_id="s", channel="c", task_summary="t",
            ...     )
            ...     updated = await registry.mark_failed(run.id)
            ...     return updated.status.value
            >>> asyncio.run(_demo())
            'failed'
        """
        return await self._transition(
            subagent_id, SubAgentStatus.FAILED, finished=True, now_ns=now_ns
        )

    async def mark_killed(self, subagent_id: str, *, now_ns: int | None = None) -> SubAgentRun:
        """Transition a row to ``killed`` (terminal — cooperative cancellation, D4).

        Args:
            subagent_id (str): Target run id.
            now_ns (int | None): Test clock override for ``finished_at``.

        Returns:
            SubAgentRun: The updated ``killed`` row.

        Examples:
            >>> import asyncio
            >>> async def _demo() -> str:
            ...     registry = SubAgentRegistry()
            ...     run = await registry.register(
            ...         level=1, role="tier_b", session_id="s", channel="c", task_summary="t",
            ...     )
            ...     updated = await registry.mark_killed(run.id)
            ...     return updated.status.value
            >>> asyncio.run(_demo())
            'killed'
        """
        return await self._transition(
            subagent_id, SubAgentStatus.KILLED, finished=True, now_ns=now_ns
        )

    async def mark_orphaned(self, subagent_id: str, *, now_ns: int | None = None) -> SubAgentRun:
        """Transition a row to ``orphaned`` (boot sweep only — no live task, D3).

        Args:
            subagent_id (str): Target run id.
            now_ns (int | None): Test clock override for ``finished_at``.

        Returns:
            SubAgentRun: The updated ``orphaned`` row.

        Examples:
            >>> import asyncio
            >>> async def _demo() -> str:
            ...     registry = SubAgentRegistry()
            ...     run = await registry.register(
            ...         level=1, role="tier_b", session_id="s", channel="c", task_summary="t",
            ...     )
            ...     updated = await registry.mark_orphaned(run.id)
            ...     return updated.status.value
            >>> asyncio.run(_demo())
            'orphaned'
        """
        return await self._transition(
            subagent_id, SubAgentStatus.ORPHANED, finished=True, now_ns=now_ns
        )

    async def running(
        self,
        *,
        level: Literal[1, 2] | None = None,
        role: Role | None = None,
    ) -> tuple[SubAgentRun, ...]:
        """Return active (``pending``/``running``) runs, optionally filtered.

        Args:
            level (Literal[1, 2] | None): Restrict to this level when given.
            role (Role | None): Restrict to this role when given.

        Returns:
            tuple[SubAgentRun, ...]: Matching active runs.

        Examples:
            >>> import asyncio
            >>> asyncio.run(SubAgentRegistry().running())
            ()
        """
        async with self._lock:
            runs = tuple(self._runs.values())
        return tuple(
            run
            for run in runs
            if run.status in ACTIVE_STATUSES
            and (level is None or run.level == level)
            and (role is None or run.role == role)
        )

    async def counts(self) -> dict[tuple[int, str], int]:
        """Active-run counts grouped by ``(level, role)`` (D3).

        Returns:
            dict[tuple[int, str], int]: Active-run count keyed by ``(level, role)``.

        Examples:
            >>> import asyncio
            >>> asyncio.run(SubAgentRegistry().counts())
            {}
        """
        async with self._lock:
            snap = self._snapshot_locked()
        return snap.counts()

    async def get(self, subagent_id: str) -> SubAgentRun | None:
        """Return one run by id, or ``None`` when unknown.

        Args:
            subagent_id (str): Run id to look up.

        Returns:
            SubAgentRun | None: The current row, or ``None``.

        Examples:
            >>> import asyncio
            >>> asyncio.run(SubAgentRegistry().get("a1f3")) is None
            True
        """
        async with self._lock:
            return self._runs.get(subagent_id)

    async def children_of(self, parent_id: str) -> tuple[SubAgentRun, ...]:
        """Return all runs (any status) with ``parent_id`` — full history.

        Args:
            parent_id (str): Level-1 run id.

        Returns:
            tuple[SubAgentRun, ...]: Matching level-2 runs, any status.

        Examples:
            >>> import asyncio
            >>> asyncio.run(SubAgentRegistry().children_of("a1f3"))
            ()
        """
        async with self._lock:
            runs = tuple(self._runs.values())
        return tuple(run for run in runs if run.parent_id == parent_id)

    async def snapshot(self) -> tuple[SubAgentRun, ...]:
        """Return every registered run (any status) — full registry dump.

        Returns:
            tuple[SubAgentRun, ...]: Every registered run, in insertion order.

        Examples:
            >>> import asyncio
            >>> asyncio.run(SubAgentRegistry().snapshot())
            ()
        """
        async with self._lock:
            return tuple(self._runs.values())
