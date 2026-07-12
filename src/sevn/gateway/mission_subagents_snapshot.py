"""Mission Control sub-agent snapshot assembly (registry + telemetry + storage).

Module: sevn.gateway.mission_subagents_snapshot
Depends: time, sevn.agent.subagents.models, sevn.agent.subagents.storage,
    sevn.config.sections.subagents

Exports:
    build_subagents_mission_snapshot — counts, running rows, limits, recent history.
Examples:
    >>> from sevn.gateway.mission_subagents_snapshot import _subagent_age_s
    >>> _subagent_age_s(0) >= 0
    True
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from sevn.agent.subagents.models import SubAgentRun
from sevn.agent.subagents.storage import list_recent_subagent_runs
from sevn.config.sections.subagents import Role, SubAgentsWorkspaceConfig, resolve_limits

if TYPE_CHECKING:
    import sqlite3

    from sevn.agent.subagents.registry import SubAgentRegistry
    from sevn.gateway.mission_state import MissionControlState

_ROLES: tuple[Role, ...] = ("triager", "tier_b", "tier_c", "tier_d")


def _subagent_age_s(started_at_ns: int, *, now_ns: int | None = None) -> float:
    """Return wall-clock age in seconds from ``started_at_ns``.

    Args:
        started_at_ns (int): Registration time in epoch nanoseconds.
        now_ns (int | None): Clock override for tests.

    Returns:
        float: Age in seconds (non-negative).

    Examples:
        >>> _subagent_age_s(time.time_ns() - 2_000_000_000) >= 1.5
        True
    """
    clock = time.time_ns() if now_ns is None else int(now_ns)
    return max(0.0, (clock - int(started_at_ns)) / 1_000_000_000.0)


def _serialize_subagent_run(run: SubAgentRun, *, now_ns: int | None = None) -> dict[str, Any]:
    """Serialize one registry row for Mission Control REST consumers.

    Args:
        run (SubAgentRun): Registry row.
        now_ns (int | None): Clock override for ``age_s``.

    Returns:
        dict[str, Any]: API row with id/role/specialist/task/status/age.

    Examples:
        >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
        >>> row = _serialize_subagent_run(SubAgentRun(
        ...     id="a1f3", level=1, role="tier_b", specialist=None, parent_id=None,
        ...     session_id="s1", channel="telegram", task_summary="hi",
        ...     status=SubAgentStatus.RUNNING, started_at=1, finished_at=None, trace_id=None,
        ... ), now_ns=2_000_000_001)
        >>> row["id"] == "a1f3" and row["age_s"] > 0
        True
    """
    return {
        "id": run.id,
        "level": run.level,
        "role": run.role,
        "specialist": run.specialist,
        "parent_id": run.parent_id,
        "session_id": run.session_id,
        "channel": run.channel,
        "task_summary": run.task_summary,
        "status": run.status.value,
        "age_s": round(_subagent_age_s(run.started_at, now_ns=now_ns), 2),
        "started_at_ns": int(run.started_at),
        "finished_at_ns": run.finished_at,
        "trace_id": run.trace_id,
    }


def _build_limits_payload(cfg: SubAgentsWorkspaceConfig | None) -> dict[str, Any]:
    """Serialize effective per-role limits for read-only Mission Control display (D2).

    Args:
        cfg (SubAgentsWorkspaceConfig | None): Workspace ``subagents`` subtree.

    Returns:
        dict[str, Any]: Defaults, override, and resolved per-role caps.

    Examples:
        >>> payload = _build_limits_payload(None)
        >>> payload["by_role"]["tier_b"]["max_level1"] == 5
        True
    """
    effective = cfg if cfg is not None else SubAgentsWorkspaceConfig()
    by_role = {
        role: {
            "max_level1": resolve_limits(effective, role)[0],
            "max_level2": resolve_limits(effective, role)[1],
        }
        for role in _ROLES
    }
    return {
        "enabled": effective.enabled,
        "max_level1_default": effective.max_level1_default,
        "max_level2_default": effective.max_level2_default,
        "max_override": effective.max_override,
        "timeout_s": effective.timeout_s,
        "by_role": by_role,
        "config_edit_path": "/mission/config",
        "config_dot_path": "subagents",
    }


async def build_subagents_mission_snapshot(
    registry: SubAgentRegistry,
    mission_state: MissionControlState,
    conn: sqlite3.Connection,
    *,
    cfg: SubAgentsWorkspaceConfig | None = None,
    recent_limit: int = 30,
    now_ns: int | None = None,
) -> dict[str, Any]:
    """Build counts + running rows + limits + recent history (W6.1).

    Args:
        registry (SubAgentRegistry): Authoritative in-memory registry (D3).
        mission_state (MissionControlState): Gateway mission aggregates (W5 telemetry).
        conn (sqlite3.Connection): Open ``sevn.db`` for terminal history (D10).
        cfg (SubAgentsWorkspaceConfig | None): Workspace ``subagents`` subtree.
        recent_limit (int): Max terminal rows from storage.
        now_ns (int | None): Clock override for ``age_s``.

    Returns:
        dict[str, Any]: Mission Control sub-agents panel payload.

    Examples:
        >>> import asyncio
        >>> import sqlite3
        >>> from sevn.agent.subagents.registry import SubAgentRegistry
        >>> from sevn.gateway.mission_state import MissionControlState
        >>> from sevn.storage.migrate import apply_migrations
        >>> async def _demo() -> int:
        ...     conn = sqlite3.connect(":memory:")
        ...     apply_migrations(conn)
        ...     snap = await build_subagents_mission_snapshot(
        ...         SubAgentRegistry(), MissionControlState(), conn,
        ...     )
        ...     return snap["counts"]["level1_total"]
        >>> asyncio.run(_demo())
        0
    """
    running_runs = await registry.running()
    counts_map = await registry.counts()
    level1_total = sum(count for (level, _role), count in counts_map.items() if level == 1)
    level2_total = sum(count for (level, _role), count in counts_map.items() if level == 2)
    by_level_role = {
        f"{level}:{role}": count for (level, role), count in sorted(counts_map.items())
    }
    gateway = mission_state.get_gateway_metrics()
    running_rows = [
        _serialize_subagent_run(run, now_ns=now_ns)
        for run in sorted(running_runs, key=lambda row: (row.level, row.role, row.id))
    ]
    recent = list_recent_subagent_runs(conn, limit=recent_limit)
    return {
        "limits": _build_limits_payload(cfg),
        "counts": {
            "by_level_role": by_level_role,
            "level1_total": level1_total,
            "level2_total": level2_total,
        },
        "telemetry": {
            "subagents_running": gateway.get("subagents_running", {}),
            "subagents_total": gateway.get("subagents_total", {}),
        },
        "running": running_rows,
        "recent": recent,
    }


__all__ = [
    "build_subagents_mission_snapshot",
]
