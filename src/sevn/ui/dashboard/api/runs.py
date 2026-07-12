"""Dashboard runs REST router.

Module: sevn.ui.dashboard.api.runs
Depends: sqlite3, fastapi, sevn.ui.dashboard.query

Exports:
    run_snapshots — active run snapshot endpoint.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request

from sevn.ui.dashboard.api.deps import require_dashboard_owner
from sevn.ui.dashboard.query import clamp_limit, list_active_run_snapshots
from sevn.ui.dashboard.services.auth import DashboardClaims

router = APIRouter(prefix="/runs", tags=["dashboard-runs"])


@router.get("/snapshots")
async def run_snapshots(
    request: Request,
    limit: int | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """List active run snapshot summaries.

    Args:
        request (Request): FastAPI request with app state.
        limit (int | None): Optional page size.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Cursor page.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_snapshots)
        True
    """

    conn: sqlite3.Connection = request.app.state.sqlite_conn
    return list_active_run_snapshots(conn, limit=clamp_limit(limit, default=50, maximum=500))
