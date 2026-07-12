"""Dashboard trace REST router.

Module: sevn.ui.dashboard.api.traces
Depends: fastapi, sevn.agent.tracing.sink_factory, sevn.storage.paths, sevn.ui.dashboard.query

Exports:
    traces_list — browse trace rows.
    traces_query — legacy alias for list route.
    trace_detail — span tree detail route.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy, redact_attrs
from sevn.agent.tracing.sink_factory import trace_redaction_policy_for
from sevn.config.defaults import DEFAULT_DASHBOARD_TRACE_LIMIT_MAX
from sevn.config.workspace_config import WorkspaceConfig
from sevn.storage.paths import traces_sqlite_path
from sevn.ui.dashboard.api.deps import require_dashboard_owner
from sevn.ui.dashboard.query import (
    clamp_limit,
    ensure_trace_connection,
    get_span_with_children,
    list_trace_events,
)
from sevn.ui.dashboard.services.auth import DashboardClaims

router = APIRouter(prefix="/traces", tags=["dashboard-traces"])


def _redact_span_row(row: dict[str, object], policy: TraceRedactionPolicy) -> dict[str, object]:
    """Apply read-path redaction to one span row before JSON serialization.

    Args:
        row (dict[str, object]): Span dict from the query layer.
        policy (TraceRedactionPolicy): Workspace redaction rules.

    Returns:
        dict[str, object]: Row with redacted ``attrs``.

    Examples:
        >>> policy = TraceRedactionPolicy.from_defaults()
        >>> out = _redact_span_row({"span_id": "s", "attrs": {"password": "x"}}, policy)
        >>> out["attrs"]["password"]
        '<redacted>'
    """

    attrs = row.get("attrs")
    if isinstance(attrs, dict):
        return {**row, "attrs": redact_attrs(dict(attrs), policy)}
    return row


def _redact_trace_page(page: dict[str, object], policy: TraceRedactionPolicy) -> dict[str, object]:
    """Redact every item in a cursor page before the HTTP response.

    Args:
        page (dict[str, object]): ``items`` / ``next_cursor`` / ``has_more`` payload.
        policy (TraceRedactionPolicy): Workspace redaction rules.

    Returns:
        dict[str, object]: Page with redacted span rows.

    Examples:
        >>> policy = TraceRedactionPolicy.from_defaults()
        >>> page = {"items": [{"span_id": "s", "attrs": {}}], "next_cursor": None, "has_more": False}
        >>> len(_redact_trace_page(page, policy)["items"])
        1
    """

    items = page.get("items")
    if not isinstance(items, list):
        return page
    redacted = [_redact_span_row(item, policy) for item in items if isinstance(item, dict)]
    return {**page, "items": redacted}


def _redact_span_tree(span: dict[str, object], policy: TraceRedactionPolicy) -> dict[str, object]:
    """Redact attrs on one span node and its nested children.

    Args:
        span (dict[str, object]): Span tree node from ``get_span_with_children``.
        policy (TraceRedactionPolicy): Workspace redaction rules.

    Returns:
        dict[str, object]: Redacted span tree.

    Examples:
        >>> policy = TraceRedactionPolicy.from_defaults()
        >>> tree = _redact_span_tree({"span_id": "r", "attrs": {}, "children": []}, policy)
        >>> tree["span_id"]
        'r'
    """

    redacted = _redact_span_row(span, policy)
    children = span.get("children")
    if isinstance(children, list):
        redacted["children"] = [
            _redact_span_tree(child, policy) for child in children if isinstance(child, dict)
        ]
    return redacted


def _parse_ts_bound(raw: str | None) -> int | None:
    """Parse optional nanosecond timestamp query values.

    Args:
        raw (str | None): Query string integer.

    Returns:
        int | None: Parsed bound or ``None`` when absent/invalid.

    Examples:
        >>> _parse_ts_bound("100") == 100
        True
        >>> _parse_ts_bound(None) is None
        True
    """

    if raw is None or not str(raw).strip():
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _trace_page(
    request: Request,
    *,
    cursor: str | None,
    limit: int | None,
    session: str | None,
    turn: str | None,
    kind: str | None,
    status: str | None,
    tier: str | None,
    budget_regime: str | None,
    model_id: str | None,
    job_id: str | None,
    ts_from: str | None,
    ts_to: str | None,
) -> dict[str, object]:
    """Load one cursor page from ``traces.db`` with read-path redaction.

    Args:
        request (Request): FastAPI request with app state.
        cursor (str | None): Optional pagination cursor.
        limit (int | None): Optional page size.
        session (str | None): Optional session id filter.
        turn (str | None): Optional turn id filter.
        kind (str | None): Optional kind filter.
        status (str | None): Optional status filter.
        tier (str | None): Optional executor tier filter.
        budget_regime (str | None): Optional ``attrs.budget_regime`` filter.
        model_id (str | None): Optional ``attrs.model_id`` filter.
        job_id (str | None): Optional ``attrs.job_id`` filter.
        ts_from (str | None): Optional inclusive lower ``ts_start_ns`` bound.
        ts_to (str | None): Optional inclusive upper ``ts_start_ns`` bound.

    Returns:
        dict[str, object]: Cursor page payload.

    Examples:
        >>> isinstance(True, bool)
        True
    """

    workspace: WorkspaceConfig = request.app.state.workspace
    policy = trace_redaction_policy_for(workspace)
    ly = request.app.state.layout
    conn = ensure_trace_connection(traces_sqlite_path(ly.dot_sevn))
    try:
        page = list_trace_events(
            conn,
            limit=clamp_limit(limit, default=50, maximum=DEFAULT_DASHBOARD_TRACE_LIMIT_MAX),
            policy=policy,
            cursor=cursor,
            session_id=session,
            turn_id=turn,
            kind=kind,
            status=status,
            tier=tier,
            budget_regime=budget_regime,
            model_id=model_id,
            job_id=job_id,
            ts_from_ns=_parse_ts_bound(ts_from),
            ts_to_ns=_parse_ts_bound(ts_to),
        )
    finally:
        conn.close()
    return _redact_trace_page(page, policy)


@router.get("")
async def traces_list(
    request: Request,
    cursor: str | None = None,
    limit: int | None = None,
    session: str | None = None,
    turn: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    tier: str | None = None,
    budget_regime: str | None = None,
    model_id: str | None = None,
    job_id: str | None = None,
    ts_from: str | None = None,
    ts_to: str | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Browse trace rows with stable ``ts_start_ns DESC`` order.

    Args:
        request (Request): FastAPI request with app state.
        cursor (str | None): Optional cursor.
        limit (int | None): Optional page size.
        session (str | None): Optional session id filter.
        turn (str | None): Optional turn id filter.
        kind (str | None): Optional kind filter.
        status (str | None): Optional status filter.
        tier (str | None): Optional executor tier filter.
        budget_regime (str | None): Optional ``attrs.budget_regime`` filter.
        model_id (str | None): Optional ``attrs.model_id`` filter.
        job_id (str | None): Optional ``attrs.job_id`` filter.
        ts_from (str | None): Optional inclusive lower ``ts_start_ns`` bound.
        ts_to (str | None): Optional inclusive upper ``ts_start_ns`` bound.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Cursor page.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(traces_list)
        True
    """

    return _trace_page(
        request,
        cursor=cursor,
        limit=limit,
        session=session,
        turn=turn,
        kind=kind,
        status=status,
        tier=tier,
        budget_regime=budget_regime,
        model_id=model_id,
        job_id=job_id,
        ts_from=ts_from,
        ts_to=ts_to,
    )


@router.get("/query")
async def traces_query(
    request: Request,
    cursor: str | None = None,
    limit: int | None = None,
    session: str | None = None,
    turn: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    tier: str | None = None,
    budget_regime: str | None = None,
    model_id: str | None = None,
    job_id: str | None = None,
    ts_from: str | None = None,
    ts_to: str | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Legacy alias for :func:`traces_list` (``GET /api/v1/traces/query``).

    Args:
        request (Request): FastAPI request with app state.
        cursor (str | None): Optional cursor.
        limit (int | None): Optional page size.
        session (str | None): Optional session id filter.
        turn (str | None): Optional turn id filter.
        kind (str | None): Optional kind filter.
        status (str | None): Optional status filter.
        tier (str | None): Optional executor tier filter.
        budget_regime (str | None): Optional ``attrs.budget_regime`` filter.
        model_id (str | None): Optional ``attrs.model_id`` filter.
        job_id (str | None): Optional ``attrs.job_id`` filter.
        ts_from (str | None): Optional inclusive lower ``ts_start_ns`` bound.
        ts_to (str | None): Optional inclusive upper ``ts_start_ns`` bound.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Cursor page.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(traces_query)
        True
    """

    return _trace_page(
        request,
        cursor=cursor,
        limit=limit,
        session=session,
        turn=turn,
        kind=kind,
        status=status,
        tier=tier,
        budget_regime=budget_regime,
        model_id=model_id,
        job_id=job_id,
        ts_from=ts_from,
        ts_to=ts_to,
    )


@router.get("/{span_id}")
async def trace_detail(
    request: Request,
    span_id: str,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return one span and its nested child tree.

    Args:
        request (Request): FastAPI request with app state.
        span_id (str): Target span id.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Span tree rooted at ``span_id``.

    Raises:
        HTTPException: ``404`` when the span id is unknown.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(trace_detail)
        True
    """

    workspace: WorkspaceConfig = request.app.state.workspace
    policy = trace_redaction_policy_for(workspace)
    ly = request.app.state.layout
    conn = ensure_trace_connection(traces_sqlite_path(ly.dot_sevn))
    try:
        detail = get_span_with_children(conn, span_id, policy=policy)
    finally:
        conn.close()
    if detail is None:
        raise HTTPException(status_code=404, detail="span_not_found")
    return {"span": _redact_span_tree(detail, policy)}


__all__ = ["trace_detail", "traces_list", "traces_query"]
