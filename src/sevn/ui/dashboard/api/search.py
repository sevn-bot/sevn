"""Dashboard unified search REST router.

Module: sevn.ui.dashboard.api.search
Depends: fastapi, sevn.ui.dashboard.query

Exports:
    global_search — ``GET /api/v1/search`` over FTS5.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from sevn.config.defaults import DEFAULT_DASHBOARD_TRACE_LIMIT_MAX
from sevn.storage.paths import traces_sqlite_path
from sevn.ui.dashboard.api.deps import require_dashboard_owner
from sevn.ui.dashboard.query import clamp_limit, ensure_trace_connection, search_trace_events
from sevn.ui.dashboard.services.auth import DashboardClaims

router = APIRouter(tags=["dashboard-search"])


@router.get("/search")
async def global_search(
    request: Request,
    q: str = "",
    limit: int | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Search traces via FTS5 (``specs/24-dashboard.md`` §2.3 global search).

    Args:
        request (Request): FastAPI request with app state.
        q (str): Free-text query.
        limit (int | None): Optional page size.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Cursor page of trace hits.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(global_search)
        True
    """

    ly = request.app.state.layout
    conn = ensure_trace_connection(traces_sqlite_path(ly.dot_sevn))
    try:
        return search_trace_events(
            conn,
            query=q,
            limit=clamp_limit(limit, default=25, maximum=DEFAULT_DASHBOARD_TRACE_LIMIT_MAX),
        )
    finally:
        conn.close()
