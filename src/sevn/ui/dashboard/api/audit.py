"""Dashboard audit trail and analytics REST router.

Module: sevn.ui.dashboard.api.audit
Depends: fastapi, sevn.agent.tracing.sink_factory, sevn.storage.paths, sevn.ui.dashboard.query

Exports:
    audit_timeline — chronological audit events.
    analytics_tool_frequency — tool-call frequency chart data.
    analytics_daily_volume — daily volume chart data.
    analytics_approvals — approval audit timeline.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy
from sevn.agent.tracing.sink_factory import trace_redaction_policy_for
from sevn.config.defaults import DEFAULT_DASHBOARD_TRACE_LIMIT_MAX
from sevn.config.workspace_config import WorkspaceConfig
from sevn.storage.paths import traces_sqlite_path
from sevn.ui.dashboard.api.deps import require_dashboard_owner
from sevn.ui.dashboard.api.traces import _redact_trace_page
from sevn.ui.dashboard.query import (
    approval_timeline_from_traces,
    audit_timeline_from_traces,
    clamp_limit,
    daily_volume_from_traces,
    ensure_trace_connection,
    tool_frequency_from_traces,
)
from sevn.ui.dashboard.services.auth import DashboardClaims

router = APIRouter(tags=["dashboard-audit"])


def _trace_policy(request: Request) -> TraceRedactionPolicy:
    """Resolve workspace trace redaction policy from app state.

    Args:
        request (Request): FastAPI request with ``workspace`` on app state.

    Returns:
        TraceRedactionPolicy: Policy for read-path redaction.

    Examples:
        >>> import inspect
        >>> "request" in inspect.signature(_trace_policy).parameters
        True
    """

    workspace: WorkspaceConfig = request.app.state.workspace
    return trace_redaction_policy_for(workspace)


@router.get("/audit/timeline")
async def audit_timeline(
    request: Request,
    limit: int | None = None,
    cursor: str | None = None,
    session_id: str | None = None,
    kind: str | None = None,
    since: int | None = None,
    until: int | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return a paginated chronological audit timeline from ``traces.db``.

    Args:
        request (Request): FastAPI request with app state.
        limit (int | None): Optional page size.
        cursor (str | None): Opaque pagination cursor.
        session_id (str | None): Optional session filter.
        kind (str | None): Optional exact trace kind filter.
        since (int | None): Inclusive lower bound ``ts_start_ns``.
        until (int | None): Inclusive upper bound ``ts_start_ns``.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Redacted cursor page of audit events.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(audit_timeline)
        True
    """

    policy = _trace_policy(request)
    ly = request.app.state.layout
    conn = ensure_trace_connection(traces_sqlite_path(ly.dot_sevn))
    try:
        page = audit_timeline_from_traces(
            conn,
            limit=clamp_limit(limit, default=50, maximum=DEFAULT_DASHBOARD_TRACE_LIMIT_MAX),
            policy=policy,
            cursor=cursor,
            session_id=session_id,
            kind=kind,
            ts_from_ns=since,
            ts_to_ns=until,
        )
        return _redact_trace_page(page, policy)
    finally:
        conn.close()


@router.get("/analytics/tool-frequency")
async def analytics_tool_frequency(
    request: Request,
    days: int = 30,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return tool-call frequency aggregates for chart rendering.

    Args:
        request (Request): FastAPI request with app state.
        days (int): Lookback window in days (1-365).
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: ``tools`` list with ``name`` and ``count``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(analytics_tool_frequency)
        True
    """

    ly = request.app.state.layout
    conn = ensure_trace_connection(traces_sqlite_path(ly.dot_sevn))
    try:
        return tool_frequency_from_traces(conn, days=days)
    finally:
        conn.close()


@router.get("/analytics/daily-volume")
async def analytics_daily_volume(
    request: Request,
    days: int = 30,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return daily event volume from ``trace_rollups_hourly``.

    Args:
        request (Request): FastAPI request with app state.
        days (int): Lookback window in days (1-365).
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: ``days`` list with ``day_start_ns`` and ``event_count``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(analytics_daily_volume)
        True
    """

    ly = request.app.state.layout
    conn = ensure_trace_connection(traces_sqlite_path(ly.dot_sevn))
    try:
        return daily_volume_from_traces(conn, days=days)
    finally:
        conn.close()


@router.get("/analytics/approvals")
async def analytics_approvals(
    request: Request,
    limit: int | None = None,
    cursor: str | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return mission approval audit timeline rows.

    Args:
        request (Request): FastAPI request with app state.
        limit (int | None): Optional page size.
        cursor (str | None): Opaque pagination cursor.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Redacted cursor page of approval events.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(analytics_approvals)
        True
    """

    policy = _trace_policy(request)
    ly = request.app.state.layout
    conn = ensure_trace_connection(traces_sqlite_path(ly.dot_sevn))
    try:
        page = approval_timeline_from_traces(
            conn,
            limit=clamp_limit(limit, default=50, maximum=DEFAULT_DASHBOARD_TRACE_LIMIT_MAX),
            policy=policy,
            cursor=cursor,
        )
        return _redact_trace_page(page, policy)
    finally:
        conn.close()


__all__ = [
    "analytics_approvals",
    "analytics_daily_volume",
    "analytics_tool_frequency",
    "audit_timeline",
    "router",
]
