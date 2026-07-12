"""Deprecated Mission Control recovery API under ``/api/v1/mission/*`` (MC-14).

Module: sevn.gateway.mission_api
Depends: fastapi

Exports:
    EmptyMissionControlState — placeholder until ``mission_state`` is fully wired.
    create_mission_v1_router — HTTP 410 + closed WebSocket for legacy recovery paths.
    resolve_mission_control_state — construct real or stub mission state.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket

_MISSION_API_DEPRECATED = (
    "Deprecated recovery routes; use /api/v1/* dashboard routes instead (MC-14)."
)


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

    Deprecated: import from :mod:`sevn.gateway.mission_trace_sink` instead.

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
    from sevn.gateway.mission_trace_sink import resolve_mission_control_state as _resolve

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
    "resolve_mission_control_state",
]
