"""Dashboard tab registry REST router (`specs/24-dashboard.md` §2.3).

Module: sevn.ui.dashboard.api.nav
Depends: fastapi, sevn.ui.dashboard.tab_registry

Exports:
    dashboard_nav — ``GET /api/v1/dashboard/nav`` SPA bootstrap payload.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from sevn.ui.dashboard.api.deps import require_dashboard_owner
from sevn.ui.dashboard.services.auth import DashboardClaims
from sevn.ui.dashboard.tab_registry import build_nav_payload

router = APIRouter(prefix="/dashboard", tags=["dashboard-nav"])


@router.get("/nav")
async def dashboard_nav(
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return Mission Control sidebar registry for SPA bootstrap.

    Args:
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Tab groups, slugs, wired set, and post-v1 placeholders.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(dashboard_nav)
        True
    """

    _ = _claims
    return build_nav_payload()
