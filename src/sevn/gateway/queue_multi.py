"""``multi`` queue-mode orchestration helpers (D6, `specs/36-sub-agents.md`).

Module: sevn.gateway.queue_multi
Depends: sevn.agent.subagents, sevn.agent.triager.relatedness

Exports:
    MultiSpawnOutcome — spawn result for ``new_task`` routing.
    MultiDispatchHooks — classify + spawn + operator-notice callbacks for enqueue.
    in_flight_task_summary_for_session — resolve the active L1 tier-B summary.
    spawn_multi_l1_via_supervisor — limit-checked level-1 tier-B spawn helper.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from loguru import logger

from sevn.agent.subagents.models import SubAgentLimitExceeded
from sevn.agent.subagents.supervisor import SubAgentSpec, SubAgentSupervisor

__all__ = [
    "MultiDispatchHooks",
    "MultiSpawnOutcome",
    "in_flight_task_summary_for_session",
    "spawn_multi_l1_via_supervisor",
]

BusyClassifyFn = Callable[[str, tuple[str, ...], str], Awaitable[tuple[str, bool]]]
SpawnL1Fn = Callable[[str, str], Awaitable["MultiSpawnOutcome"]]
NotifyOperatorFn = Callable[[str, str], Awaitable[None]]


class MultiSpawnOutcome(StrEnum):
    """Outcome of a ``new_task`` spawn attempt (D5/D6)."""

    SPAWNED = "spawned"
    LIMIT_STEER = "limit_steer"


@dataclass(frozen=True, slots=True)
class MultiDispatchHooks:
    """Callbacks :meth:`sevn.gateway.session_manager.SessionManager.enqueue_dispatch` uses."""

    classify_busy: BusyClassifyFn
    spawn_new_task: SpawnL1Fn
    notify_operator: NotifyOperatorFn


async def in_flight_task_summary_for_session(
    supervisor: SubAgentSupervisor | None,
    session_id: str,
) -> str:
    """Return the task summary of the primary in-flight L1 tier-B run, if any.

    Args:
        supervisor (SubAgentSupervisor | None): Process supervisor (``None`` → empty).
        session_id (str): Gateway session id.

    Returns:
        str: Best-effort in-flight summary, or ``""`` when none is active.

    Examples:
        >>> import asyncio
        >>> asyncio.run(in_flight_task_summary_for_session(None, "s"))
        ''
    """
    if supervisor is None:
        return ""
    active = await supervisor.registry.running(level=1, role="tier_b")
    for run in active:
        if run.session_id == session_id and run.task_summary.strip():
            return run.task_summary.strip()
    for run in active:
        if run.session_id == session_id:
            return run.task_summary.strip()
    return ""


async def spawn_multi_l1_via_supervisor(
    supervisor: SubAgentSupervisor,
    *,
    session_id: str,
    channel: str,
    task_summary: str,
    body: Callable[[], Awaitable[object]],
) -> MultiSpawnOutcome:
    """Spawn one level-1 tier-B run via the supervisor limit-checked path (D5).

    Args:
        supervisor (SubAgentSupervisor): Process supervisor.
        session_id (str): Gateway session id.
        channel (str): Channel name.
        task_summary (str): Short human-readable task line.
        body (Callable[[], Awaitable[object]]): Async work callable.

    Returns:
        MultiSpawnOutcome: ``SPAWNED`` or ``LIMIT_STEER`` when capped.

    Examples:
        >>> import asyncio
        >>> from sevn.agent.subagents.registry import SubAgentRegistry
        >>> async def _demo() -> MultiSpawnOutcome:
        ...     sup = SubAgentSupervisor(SubAgentRegistry())
        ...     async def _work() -> str:
        ...         return "ok"
        ...     return await spawn_multi_l1_via_supervisor(
        ...         sup,
        ...         session_id="s",
        ...         channel="webchat",
        ...         task_summary="t",
        ...         body=_work,
        ...     )
        >>> asyncio.run(_demo())
        <MultiSpawnOutcome.SPAWNED: 'spawned'>
    """
    spec = SubAgentSpec(
        level=1,
        role="tier_b",
        body=body,
        session_id=session_id,
        channel=channel,
        task_summary=task_summary,
    )
    result = await supervisor.spawn(spec)
    if isinstance(result, SubAgentLimitExceeded):
        logger.info(
            "queue_multi_spawn_limit_exceeded session_id={} role={} current={} limit={}",
            session_id,
            result.role,
            result.current,
            result.limit,
        )
        return MultiSpawnOutcome.LIMIT_STEER
    return MultiSpawnOutcome.SPAWNED
