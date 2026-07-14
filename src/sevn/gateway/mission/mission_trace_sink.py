"""Gateway trace subscriber that feeds :class:`~sevn.gateway.mission.mission_state.MissionControlState`.

Module: sevn.gateway.mission.mission_trace_sink
Depends: sevn.agent.tracing.emit, sevn.gateway.mission.mission_state, sevn.gateway.mission.mission_state_models

Exports:
    MissionControlTraceSink — ``TraceSink`` forwarding gateway spans into mission state.
    create_mission_trace_sink — build subscriber + register with tracing emit.
    detach_mission_trace_sink — unregister a mission trace subscriber.
    resolve_mission_control_state — shared accessor for ``app.state`` mission state.
Examples:
    >>> from sevn.gateway.mission.mission_state import MissionControlState
    >>> from sevn.gateway.mission.mission_trace_sink import create_mission_trace_sink
    >>> isinstance(create_mission_trace_sink(MissionControlState()), object)
    True
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sevn.agent.tracing.emit import register_trace_subscriber, unregister_trace_subscriber
from sevn.gateway.mission.mission_state_models import (
    GATEWAY_TRACE_KINDS,
    is_mission_telemetry_kind,
)

if TYPE_CHECKING:
    from fastapi import Request

    from sevn.agent.tracing.sink import TraceEvent
    from sevn.gateway.mission.mission_state import MissionControlState


class MissionControlTraceSink:
    """``TraceSink`` that forwards gateway span kinds into :class:`MissionControlState`."""

    def __init__(self, state: MissionControlState) -> None:
        """Attach mission state for trace consumption.

        Args:
            state (MissionControlState): Shared state instance.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        self._state = state

    async def emit(self, event: TraceEvent) -> None:
        """Apply gateway trace rows to mission state (never raises).

        Args:
            event (TraceEvent): Structured trace row.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MissionControlTraceSink.emit)
            True
        """
        if event.kind in GATEWAY_TRACE_KINDS:
            await self._state.apply_trace_event(event)
        elif is_mission_telemetry_kind(event.kind):
            await self._state.apply_telemetry_trace_event(event)

    async def flush(self) -> None:
        """No buffered state.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        return

    async def close(self) -> None:
        """No persistent resources.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        return


def create_mission_trace_sink(state: MissionControlState) -> MissionControlTraceSink:
    """Build a trace subscriber and register it with :mod:`sevn.agent.tracing.emit`.

    Args:
        state (MissionControlState): Shared Mission Control instance (gateway app state).
    Returns:
        MissionControlTraceSink: Registered subscriber; pass to
        :func:`~sevn.gateway.mission.mission_trace_sink.detach_mission_trace_sink` on teardown.
    Examples:
        >>> from sevn.gateway.mission.mission_state import MissionControlState
        >>> sink = create_mission_trace_sink(MissionControlState())
        >>> isinstance(sink, MissionControlTraceSink)
        True
    """
    sink = MissionControlTraceSink(state)
    register_trace_subscriber(sink)
    return sink


def detach_mission_trace_sink(sink: MissionControlTraceSink) -> None:
    """Unregister a mission trace subscriber installed by :func:`create_mission_trace_sink`.

    Args:
        sink (MissionControlTraceSink): Previously registered subscriber.
    Examples:
        >>> from sevn.gateway.mission.mission_state import MissionControlState
        >>> detach_mission_trace_sink(create_mission_trace_sink(MissionControlState())) is None
        True
    """
    unregister_trace_subscriber(sink)


def resolve_mission_control_state(request: Request | None = None) -> Any:
    """Return gateway ``app.state`` mission state when wired, else a fresh instance.

    Args:
        request (Request | None): Active HTTP request; when set, prefers
            ``request.app.state.mission_control_state`` from gateway lifespan.

    Returns:
        Any: Shared mission state from ``app.state`` or a new
        :class:`~sevn.gateway.mission.mission_state.MissionControlState`.

    Examples:
        >>> state = resolve_mission_control_state()
        >>> callable(getattr(state, "get_activity_feed", None))
        True
    """
    if request is not None:
        existing = getattr(request.app.state, "mission_control_state", None)
        if existing is not None:
            return existing
    from sevn.gateway.mission.mission_state import MissionControlState

    return MissionControlState()


__all__ = [
    "MissionControlTraceSink",
    "create_mission_trace_sink",
    "detach_mission_trace_sink",
    "resolve_mission_control_state",
]
