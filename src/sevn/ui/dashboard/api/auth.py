"""Dashboard auth REST router.

Module: sevn.ui.dashboard.api.auth
Depends: fastapi, pydantic, sevn.ui.dashboard.services.auth

Exports:
    LoginRequest — owner login request body.
    auth_status — report local-open vs auth-required for SPA boot.
    login — create an httpOnly dashboard session.
    logout — clear the dashboard session.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from sevn.config.workspace_config import WorkspaceConfig
from sevn.ui.dashboard.api.deps import require_dashboard_csrf
from sevn.ui.dashboard.services.auth import (
    DASHBOARD_COOKIE_NAME,
    DASHBOARD_CSRF_COOKIE_NAME,
    DashboardAuthService,
    local_open_effective,
    sevn_json_path_from_request,
    tunnel_active,
)

router = APIRouter(prefix="/auth", tags=["dashboard-auth"])


@router.get("/status")
async def auth_status(request: Request) -> dict[str, bool]:
    """Report whether Mission Control requires owner login for this client.

    Args:
        request (Request): Incoming HTTP request (loopback vs remote).

    Returns:
        dict[str, bool]: ``auth_required``, ``local_open``, ``tunnel_active``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(auth_status)
        True
    """

    workspace: WorkspaceConfig = request.app.state.workspace
    local_open = local_open_effective(workspace, request)
    return {
        "auth_required": not local_open,
        "local_open": local_open,
        "tunnel_active": tunnel_active(
            workspace,
            sevn_json=sevn_json_path_from_request(request),
        ),
    }


class LoginRequest(BaseModel):
    """Owner login request body."""

    model_config = ConfigDict(extra="ignore")

    password: str
    totp: str | None = None


@router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, object]:
    """Create an httpOnly dashboard session cookie.

    Args:
        payload (LoginRequest): Password/TOTP-shaped login body.
        request (Request): FastAPI request with app state.
        response (Response): Response used to set cookie headers.

    Returns:
        dict[str, object]: Bearer-compatible token payload for API clients.

    Raises:
        HTTPException: ``401`` on bad credentials or ``503`` when unconfigured.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(login)
        True
    """

    service: DashboardAuthService = request.app.state.dashboard_auth_service
    workspace: WorkspaceConfig = request.app.state.workspace
    if not service.can_login(workspace):
        raise HTTPException(status_code=503, detail="dashboard_login_unconfigured")
    if not service.verify_login(password=payload.password, workspace=workspace):
        raise HTTPException(status_code=401, detail="unauthorized")
    token, expires_in = service.mint_dashboard_jwt(workspace=workspace)
    csrf = service.mint_csrf_token()
    is_https = (
        request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https"
    )
    response.set_cookie(
        DASHBOARD_COOKIE_NAME,
        token,
        max_age=expires_in,
        httponly=True,
        samesite="lax",
        secure=is_https,
    )
    response.set_cookie(
        DASHBOARD_CSRF_COOKIE_NAME,
        csrf,
        max_age=expires_in,
        httponly=False,
        samesite="lax",
        secure=is_https,
    )
    return {
        "access_token": token,
        "token_type": "Bearer",  # nosec B105 — OAuth 2.0 token type constant (RFC 6749)
        "expires_in": expires_in,
        "csrf_token": csrf,
    }


@router.post("/logout")
async def logout(
    response: Response,
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, bool]:
    """Clear the dashboard session cookie.

    Args:
        response (Response): Response used to clear cookie headers.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        dict[str, bool]: Logout status.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(logout)
        True
    """

    response.delete_cookie(DASHBOARD_COOKIE_NAME)
    response.delete_cookie(DASHBOARD_CSRF_COOKIE_NAME)
    return {"ok": True}
