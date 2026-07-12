"""Dashboard channels and alert rollup REST routers (`specs/24-dashboard.md` MC-5).

Module: sevn.ui.dashboard.api.channels
Depends: asyncio, sqlite3, fastapi, sevn.agent.tracing.redacting_sink, sevn.ui.dashboard.api.deps, sevn.ui.dashboard.query

Exports:
    channels_status — channel config + runtime health + session counts.
    channels_config_get — editable channel enablement/routing toggles.
    channels_config_put — patch the ``channels`` subtree in ``sevn.json``.
    alerts_rollup — mission alerts + recent error traces.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from sevn.agent.tracing.sink_factory import trace_redaction_policy_for
from sevn.config.workspace_config import ChannelsWorkspaceSectionConfig, WorkspaceConfig
from sevn.storage.paths import traces_sqlite_path
from sevn.ui.dashboard.api._config_persist import (
    config_error,
    config_validation_error,
    deep_merge,
    load_workspace_document,
    persist_workspace_document,
    read_config_body,
)
from sevn.ui.dashboard.api.deps import require_dashboard_csrf, require_dashboard_owner
from sevn.ui.dashboard.query import clamp_limit, ensure_trace_connection, list_trace_events
from sevn.ui.dashboard.services.auth import DashboardClaims
from sevn.ui.dashboard.services.mission_runtime import (
    mission_runtime_alerts,
    mission_runtime_channels,
)
from sevn.workspace.layout import WorkspaceLayout

router = APIRouter(prefix="/channels", tags=["dashboard-channels"])
alerts_router = APIRouter(prefix="/alerts", tags=["dashboard-alerts"])


def _channel_enabled_flags(workspace: WorkspaceConfig) -> dict[str, bool]:
    """Read ``channels.<name>.enabled`` from workspace config.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.

    Returns:
        dict[str, bool]: Channel name to enabled flag.

    Examples:
        >>> _channel_enabled_flags(WorkspaceConfig.minimal())
        {}
    """

    ch = workspace.channels
    if ch is None:
        return {}
    dumped = ch.model_dump(mode="python")
    out: dict[str, bool] = {}
    for name, blob in dumped.items():
        if isinstance(blob, dict):
            out[str(name)] = bool(blob.get("enabled", False))
    return out


def _session_counts_by_channel(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Aggregate gateway session rows grouped by channel.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.

    Returns:
        dict[str, dict[str, Any]]: Per-channel session stats.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _session_counts_by_channel(c) == {}
        True
        >>> c.close()
    """

    rows = conn.execute(
        """
        SELECT channel, COUNT(1) AS session_count, MAX(updated_at) AS last_activity
        FROM gateway_sessions
        GROUP BY channel
        """,
    ).fetchall()
    return {
        str(row[0]): {
            "session_count": int(row[1] or 0),
            "last_activity": str(row[2] or ""),
        }
        for row in rows
    }


def _merge_channel_rows(
    *,
    enabled: dict[str, bool],
    runtime: dict[str, Any],
    sessions: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge config, mission runtime health, and session aggregates.

    Args:
        enabled (dict[str, bool]): Configured channel enable flags.
        runtime (dict[str, Any]): ``MissionControlState.get_status()`` channel map.
        sessions (dict[str, dict[str, Any]]): Session counts keyed by channel.

    Returns:
        list[dict[str, Any]]: Sorted channel status rows.

    Examples:
        >>> rows = _merge_channel_rows(
        ...     enabled={"telegram": True},
        ...     runtime={"telegram": {"connected": True, "connection_state": "ok"}},
        ...     sessions={"telegram": {"session_count": 2, "last_activity": "t"}},
        ... )
        >>> rows[0]["name"] == "telegram" and rows[0]["session_count"] == 2
        True
    """

    names = sorted(set(enabled) | set(runtime) | set(sessions))
    rows: list[dict[str, Any]] = []
    for name in names:
        raw_rt = runtime.get(name)
        rt: dict[str, Any] = raw_rt if isinstance(raw_rt, dict) else {}
        sess = sessions.get(name, {})
        rows.append(
            {
                "name": name,
                "enabled": enabled.get(name, False),
                "connected": bool(rt.get("connected", False)),
                "connection_state": str(rt.get("connection_state") or "unknown"),
                "adapter_type": str(rt.get("adapter_type") or ""),
                "messages": int(rt.get("messages") or 0),
                "errors": int(rt.get("errors") or 0),
                "reconnects": int(rt.get("reconnects") or 0),
                "last_error": str(rt.get("last_error") or ""),
                "session_count": int(sess.get("session_count") or 0),
                "last_activity": str(sess.get("last_activity") or ""),
            },
        )
    return rows


@router.get("/status")
async def channels_status(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return channel enablement, runtime health, and session counts.

    Args:
        request (Request): FastAPI request with workspace and sqlite state.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: ``channels`` list and ``generated_at_ns``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(channels_status)
        True
    """

    workspace: WorkspaceConfig = request.app.state.workspace
    conn: sqlite3.Connection = request.app.state.sqlite_conn
    enabled = _channel_enabled_flags(workspace)
    runtime = mission_runtime_channels(request)
    sessions = await asyncio.to_thread(_session_counts_by_channel, conn)
    channels = _merge_channel_rows(enabled=enabled, runtime=runtime, sessions=sessions)
    return {"channels": channels, "generated_at_ns": time.time_ns()}


@alerts_router.get("/rollup")
async def alerts_rollup(
    request: Request,
    limit: int | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return mission alerts plus recent error spans from traces.

    Args:
        request (Request): FastAPI request with layout and workspace.
        limit (int | None): Page size for trace errors and mission alerts.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: ``mission_alerts``, ``trace_errors``, ``logs_dir``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(alerts_rollup)
        True
    """

    workspace: WorkspaceConfig = request.app.state.workspace
    layout: WorkspaceLayout = request.app.state.layout
    page_limit = clamp_limit(limit, default=25, maximum=100)
    mission_rows = mission_runtime_alerts(request, limit=page_limit)
    policy = trace_redaction_policy_for(workspace)
    ly = request.app.state.layout

    def _trace_errors() -> list[dict[str, object]]:
        conn = ensure_trace_connection(traces_sqlite_path(ly.dot_sevn))
        try:
            page = list_trace_events(
                conn,
                limit=page_limit,
                policy=policy,
                status="error",
            )
            items = page.get("items")
            return list(items) if isinstance(items, list) else []
        finally:
            conn.close()

    trace_rows = await asyncio.to_thread(_trace_errors)
    return {
        "mission_alerts": mission_rows,
        "trace_errors": trace_rows,
        "logs_dir": str(layout.logs_dir),
        "proxy_log": str(layout.logs_dir / "proxy.log"),
    }


def _channels_config_payload(workspace: WorkspaceConfig) -> dict[str, object]:
    """Project the editable ``channels`` enablement/routing toggles.

    Args:
        workspace (WorkspaceConfig): Active workspace config.

    Returns:
        dict[str, object]: Telegram/webchat editable fields (no secret refs).

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_channels_config_payload)
        True
    """

    channels = workspace.channels
    telegram = channels.telegram if channels else None
    webchat = channels.webchat if channels else None
    return {
        "channels": {
            "telegram": {
                "enabled": telegram.enabled if telegram else None,
                "mode": telegram.mode if telegram else None,
                "dm_policy": telegram.dm_policy if telegram else None,
            },
            "webchat": {
                "enabled": webchat.enabled if webchat else None,
                "public": webchat.public if webchat else None,
            },
        },
    }


@router.get("/config")
async def channels_config_get(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> JSONResponse:
    """Return editable ``channels`` toggles for the Channels tab.

    Args:
        request (Request): Starlette request with workspace state.
        _claims (DashboardClaims): Verified owner claims.

    Returns:
        JSONResponse: Editable channel toggle projection.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(channels_config_get)
        True
    """

    workspace: WorkspaceConfig = request.app.state.workspace
    return JSONResponse(status_code=200, content=_channels_config_payload(workspace))


@router.put("/config")
async def channels_config_put(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Patch the ``channels`` subtree in ``sevn.json`` from a partial body.

    Args:
        request (Request): JSON body with a ``channels`` object.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: Updated payload, ``400`` on bad body, ``422`` on schema failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(channels_config_put)
        True
    """

    body = await read_config_body(request)
    patch = body.get("channels")
    if not isinstance(patch, dict):
        return config_error("invalid_body", "body.channels must be a JSON object", status_code=400)
    on_disk = load_workspace_document(request)
    merged = deep_merge(dict(on_disk.get("channels") or {}), patch)
    try:
        validated = ChannelsWorkspaceSectionConfig.model_validate(merged)
    except ValidationError as exc:
        return config_validation_error(exc)
    on_disk["channels"] = validated.model_dump(mode="python", exclude_none=True)
    try:
        ws = persist_workspace_document(request, on_disk)
    except (ValidationError, ValueError, OSError) as exc:
        return config_validation_error(exc)
    return JSONResponse(status_code=200, content=_channels_config_payload(ws))


__all__ = [
    "alerts_rollup",
    "alerts_router",
    "channels_config_get",
    "channels_config_put",
    "channels_status",
    "router",
]
