"""Deprecated Mission Control recovery API under ``/api/v1/mission/*`` (MC-14).

Module: sevn.gateway.mission.mission_api
Depends: fastapi, sevn.agent.subagents, sevn.gateway.mission.mission_subagents_snapshot,
    sevn.gateway.mission.mission_trace_sink

Exports:
    EmptyMissionControlState — placeholder until ``mission_state`` is fully wired.
    create_mission_v1_router — HTTP 410 + closed WebSocket for legacy recovery paths.
    resolve_mission_control_state — construct real or stub mission state.
    fetch_subagents_mission_payload — W6 snapshot for dashboard ops routes.
    kill_subagent_mission — cooperative kill via process supervisor (D4/D13).
    kill_all_subagents_mission — kill-all scoped to optional role (D13).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request, WebSocket

from sevn.config.sections.subagents import Role
from sevn.gateway.mission.mission_subagents_snapshot import build_subagents_mission_snapshot
from sevn.gateway.mission.mission_trace_sink import (
    resolve_mission_control_state as _trace_resolve_mission_control_state,
)

if TYPE_CHECKING:
    from sevn.agent.subagents.supervisor import SubAgentSupervisor

_MISSION_API_DEPRECATED = (
    "Deprecated recovery routes; use /api/v1/* dashboard routes instead (MC-14)."
)

_VALID_ROLES: frozenset[str] = frozenset({"triager", "tier_b", "tier_c", "tier_d"})


def _resolve_subagent_supervisor(request: Request) -> SubAgentSupervisor | None:
    """Return the gateway process supervisor when boot wired it (W2.5).

    Args:
        request (Request): Active HTTP request.

    Returns:
        SubAgentSupervisor | None: Shared supervisor or ``None`` when absent.

    Examples:
        >>> _resolve_subagent_supervisor.__name__
        '_resolve_subagent_supervisor'
    """
    supervisor = getattr(request.app.state, "subagent_supervisor", None)
    return supervisor if supervisor is not None else None


async def fetch_subagents_mission_payload(
    request: Request,
    *,
    recent_limit: int = 30,
) -> dict[str, Any]:
    """Build the Mission Control sub-agents panel snapshot (W6.1/W6.2).

    Args:
        request (Request): Active HTTP request with registry/supervisor on ``app.state``.
        recent_limit (int): Max terminal history rows from storage.

    Returns:
        dict[str, Any]: Counts, running rows, limits, telemetry, and recent history.

    Raises:
        HTTPException: When the sub-agent supervisor is not boot-wired.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(fetch_subagents_mission_payload)
        True
    """
    supervisor = _resolve_subagent_supervisor(request)
    if supervisor is None:
        raise HTTPException(status_code=503, detail="subagent supervisor unavailable")
    conn = getattr(request.app.state, "sqlite_conn", None)
    if conn is None:
        raise HTTPException(status_code=503, detail="sqlite connection unavailable")
    workspace = getattr(request.app.state, "workspace", None)
    cfg = getattr(workspace, "subagents", None) if workspace is not None else None
    mission_state = _trace_resolve_mission_control_state(request)
    return await build_subagents_mission_snapshot(
        supervisor.registry,
        mission_state,
        conn,
        cfg=cfg,
        recent_limit=recent_limit,
    )


async def kill_subagent_mission(request: Request, subagent_id: str) -> dict[str, Any]:
    """Kill one sub-agent run through the process supervisor (D4/D13).

    Args:
        request (Request): Active HTTP request.
        subagent_id (str): Short run id.

    Returns:
        dict[str, Any]: Kill outcome with updated row when known.

    Raises:
        HTTPException: When supervisor/registry unavailable or id unknown.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(kill_subagent_mission)
        True
    """
    supervisor = _resolve_subagent_supervisor(request)
    if supervisor is None:
        raise HTTPException(status_code=503, detail="subagent supervisor unavailable")
    run = await supervisor.registry.get(subagent_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"subagent not found: {subagent_id}")
    killed = await supervisor.kill(subagent_id, cascade=True)
    updated = await supervisor.registry.get(subagent_id)
    return {
        "id": subagent_id,
        "killed": killed,
        "status": updated.status.value if updated is not None else run.status.value,
    }


async def kill_all_subagents_mission(
    request: Request,
    *,
    role: str | None = None,
) -> dict[str, Any]:
    """Kill all active level-1 sub-agents, optionally scoped to one role (D13).

    Args:
        request (Request): Active HTTP request.
        role (str | None): Optional level-1 role filter.

    Returns:
        dict[str, Any]: Number of runs cancelled.

    Raises:
        HTTPException: When supervisor unavailable or role invalid.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(kill_all_subagents_mission)
        True
    """
    supervisor = _resolve_subagent_supervisor(request)
    if supervisor is None:
        raise HTTPException(status_code=503, detail="subagent supervisor unavailable")
    role_filter: Role | None = None
    if role is not None:
        role_s = role.strip()
        if role_s:
            if role_s not in _VALID_ROLES:
                raise HTTPException(status_code=400, detail=f"unknown subagents role: {role_s}")
            role_filter = role_s  # type: ignore[assignment]
    count = await supervisor.kill_all(role=role_filter)
    return {"killed_count": count, "role": role_filter}


class EmptyMissionControlState:
    """Placeholder ``MissionControlState`` until Wave C1 ``mission_state`` merges."""

    def get_activity_feed(self, limit: int = 50, event_type: str = "") -> list[dict[str, Any]]:
        """Return an empty activity feed.

        Args:
            limit (int): Ignored for the empty stub.
            event_type (str): Ignored for the empty stub.

        Returns:
            list[dict[str, Any]]: Always empty.

        Examples:
            >>> EmptyMissionControlState().get_activity_feed()
            []
        """

        _ = limit, event_type
        return []

    def get_status(self) -> dict[str, Any]:
        """Return an empty mission status snapshot.

        Returns:
            dict[str, Any]: Empty mapping.

        Examples:
            >>> EmptyMissionControlState().get_status()
            {}
        """

        return {}


def resolve_mission_control_state(request: Request | None = None) -> Any:
    """Return gateway ``app.state`` mission state when wired, else a fresh instance.

    Deprecated: import from :mod:`sevn.gateway.mission.mission_trace_sink` instead.

    Args:
        request (Request | None): Active HTTP request; when set, prefers
            ``request.app.state.mission_control_state`` from gateway lifespan.

    Returns:
        Any: Shared mission state from ``app.state``, ``mission_state`` module,
            or :class:`EmptyMissionControlState`.

    Examples:
        >>> state = resolve_mission_control_state()
        >>> callable(getattr(state, "get_activity_feed", None))
        True
    """
    from sevn.gateway.mission.mission_trace_sink import resolve_mission_control_state as _resolve

    return _resolve(request)


def create_mission_v1_router() -> APIRouter:
    """Register deprecated Mission Control recovery routes (HTTP 410).

    Args:
        None.

    Returns:
        APIRouter: Legacy ``/api/v1/mission/*`` paths that always return gone.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(create_mission_v1_router)
        True
    """

    router = APIRouter(prefix="/api/v1/mission", tags=["mission-v1-deprecated"])

    @router.get("/sessions")
    @router.get("/sessions/{session_id}")
    @router.get("/providers/health")
    async def mission_deprecated_http() -> None:
        """Legacy recovery HTTP endpoints (SPA uses ``/api/v1/*``)."""
        raise HTTPException(status_code=410, detail=_MISSION_API_DEPRECATED)

    @router.websocket("/activity")
    async def mission_deprecated_activity(websocket: WebSocket) -> None:
        """Legacy activity WebSocket (dashboard uses ``/ws/dashboard``)."""
        await websocket.close(code=1008, reason="deprecated")

    return router


__all__ = [
    "EmptyMissionControlState",
    "create_mission_v1_router",
    "fetch_subagents_mission_payload",
    "kill_all_subagents_mission",
    "kill_subagent_mission",
    "resolve_mission_control_state",
]
