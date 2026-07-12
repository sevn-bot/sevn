"""FastAPI dependencies for Mission Control routers.

Module: sevn.ui.dashboard.api.deps
Depends: fastapi, sevn.ui.dashboard.services.auth

Exports:
    require_dashboard_owner — verify ``aud=dashboard`` auth.
    require_dashboard_csrf — verify double-submit CSRF for mutating routes.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from sevn.config.workspace_config import WorkspaceConfig
from sevn.ui.dashboard.services.auth import (
    DASHBOARD_COOKIE_NAME,
    DASHBOARD_CSRF_COOKIE_NAME,
    DASHBOARD_CSRF_HEADER,
    DashboardAuthService,
    DashboardClaims,
    local_open_effective,
    synthetic_owner_claims,
)


async def require_dashboard_owner(request: Request) -> DashboardClaims:
    """Require an owner dashboard JWT from cookie or bearer header.

    Args:
        request (Request): Incoming HTTP request.

    Returns:
        DashboardClaims: Verified dashboard claims.

    Raises:
        HTTPException: ``401`` when the token is missing or invalid.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(require_dashboard_owner)
        True
    """

    workspace: WorkspaceConfig = request.app.state.workspace
    if local_open_effective(workspace, request):
        return synthetic_owner_claims(workspace)

    service: DashboardAuthService = request.app.state.dashboard_auth_service
    token = service.token_from_request(
        authorization=request.headers.get("Authorization"),
        cookie=request.cookies.get(DASHBOARD_COOKIE_NAME),
    )
    if not token:
        raise HTTPException(status_code=401, detail="unauthorized")
    claims = service.verify_dashboard_jwt(token)
    if claims is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    return claims


async def require_dashboard_csrf(request: Request) -> None:
    """Require matching CSRF cookie and header on mutating dashboard routes.

    Anonymous loopback ``local_open`` sessions skip CSRF (same trust boundary as
    synthetic owner claims). Logged-in dashboard sessions still require CSRF.

    Args:
        request (Request): Incoming HTTP request.

    Raises:
        HTTPException: ``403`` when CSRF verification fails.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(require_dashboard_csrf)
        True
    """

    workspace: WorkspaceConfig = request.app.state.workspace
    service: DashboardAuthService = request.app.state.dashboard_auth_service
    if local_open_effective(workspace, request):
        token = service.token_from_request(
            authorization=request.headers.get("Authorization"),
            cookie=request.cookies.get(DASHBOARD_COOKIE_NAME),
        )
        if not token or service.verify_dashboard_jwt(token) is None:
            return

    if not service.verify_csrf(
        cookie=request.cookies.get(DASHBOARD_CSRF_COOKIE_NAME),
        header=request.headers.get(DASHBOARD_CSRF_HEADER),
    ):
        raise HTTPException(status_code=403, detail="csrf_failed")
