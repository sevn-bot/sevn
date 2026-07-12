"""Mission Control audit trace + hub notifications for mutating dashboard APIs.

Module: sevn.ui.dashboard.services.mission_audit
Depends: time, uuid, fastapi, sevn.agent.tracing.sink, sevn.ui.dashboard.ws

Exports:
    emit_mission_audit — persist trace row and publish hub event (no secret content).
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any

from sevn.agent.tracing.sink import SYSTEM_TURN_ID, TraceEvent, TraceSink
from sevn.ui.dashboard.ws import DashboardHub

if TYPE_CHECKING:
    from fastapi import Request


async def emit_mission_audit(
    request: Request,
    *,
    kind: str,
    path: str | None = None,
    byte_count: int | None = None,
    op: str | None = None,
    alias: str | None = None,
    hub_type: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit a mission audit trace and optional ``DashboardHub`` event.

    Args:
        request (Request): FastAPI request (trace sink + hub on ``app.state``).
        kind (str): Trace kind (e.g. ``mission.file.write``).
        path (str | None): Workspace-relative path (never file content).
        byte_count (int | None): Written byte count when applicable.
        op (str | None): Operation name (create/write/delete/rename).
        alias (str | None): Secret alias for secrets audit rows.
        hub_type (str | None): Hub event ``type`` override.
        extra (dict[str, Any] | None): Additional safe attrs (no secrets).

    Returns:
        None: Side-effect only.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(emit_mission_audit)
        True
    """
    attrs: dict[str, Any] = {}
    if path is not None:
        attrs["path"] = path
    if byte_count is not None:
        attrs["byte_count"] = byte_count
    if op is not None:
        attrs["op"] = op
    if alias is not None:
        attrs["alias"] = alias
    if extra:
        attrs.update(extra)

    sink: TraceSink | None = getattr(request.app.state, "gateway_trace", None)
    if sink is not None:
        now = time.time_ns()
        event = TraceEvent(
            kind=kind,
            span_id=str(uuid.uuid4()),
            parent_span_id=None,
            session_id="dashboard",
            turn_id=SYSTEM_TURN_ID,
            tier=None,
            ts_start_ns=now,
            ts_end_ns=now,
            status="ok",
            attrs=attrs,
        )
        await sink.emit(event)

    hub: DashboardHub | None = getattr(request.app.state, "dashboard_hub", None)
    if hub is not None:
        topic = "mission.file"
        if kind.startswith("mission.secrets."):
            topic = "mission.secrets"
        elif kind.startswith("mission."):
            topic = kind.split(".", 2)[1] if kind.count(".") >= 2 else "mission"
        payload: dict[str, Any] = {"kind": kind}
        if hub_type is not None:
            payload["event_type"] = hub_type
        elif kind.startswith("mission.file."):
            payload["event_type"] = "mission.file.changed"
        elif kind.startswith("mission.secrets."):
            payload["event_type"] = "mission.secrets.changed"
        if path is not None:
            payload["path"] = path
        if alias is not None:
            payload["alias"] = alias
        if extra:
            payload.update(extra)
        await hub.publish(topic, payload)


__all__ = ["emit_mission_audit"]
