"""Shared Mission Control runtime accessors for dashboard routes.

Module: sevn.ui.dashboard.services.mission_runtime
Depends: fastapi, sevn.gateway.mission_trace_sink

Exports:
    mission_runtime_channels — channel health map from gateway mission state.
    mission_runtime_alerts — alert rows from gateway mission state.
Examples:
    >>> mission_runtime_channels.__name__
    'mission_runtime_channels'
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sevn.gateway.mission_trace_sink import resolve_mission_control_state

if TYPE_CHECKING:
    from fastapi import Request


def mission_runtime_channels(request: Request) -> dict[str, Any]:
    """Return live channel health from gateway mission state when present.

    Args:
        request (Request): FastAPI request with optional ``mission_control_state``.

    Returns:
        dict[str, Any]: Channel name to runtime health mapping.

    Examples:
        >>> mission_runtime_channels.__name__
        'mission_runtime_channels'
    """
    state = resolve_mission_control_state(request)
    status = state.get_status()
    channels = status.get("channels")
    return channels if isinstance(channels, dict) else {}


def mission_runtime_alerts(request: Request, *, limit: int) -> list[dict[str, Any]]:
    """Return mission-control alert rows when state is wired.

    Args:
        request (Request): FastAPI request with optional ``mission_control_state``.
        limit (int): Maximum rows to return.

    Returns:
        list[dict[str, Any]]: Newest-first alert rows.

    Examples:
        >>> mission_runtime_alerts.__name__
        'mission_runtime_alerts'
    """
    state = resolve_mission_control_state(request)
    if not callable(getattr(state, "get_alerts", None)):
        return []
    rows = state.get_alerts(unacknowledged_only=False)
    return list(rows[:limit])


__all__ = ["mission_runtime_alerts", "mission_runtime_channels"]
