"""Mission Control in-dashboard webchat console API (MC W6).

Module: sevn.ui.dashboard.api.chat
Depends: time, fastapi, sevn.gateway.auth, sevn.ui.dashboard.api.deps

Exports:
    chat_token — server-mint webchat JWT for the verified dashboard owner.
    chat_fork — rotate the owner webchat session scope (new conversation).
    ChatTokenResponse — ``POST /chat/token`` response schema.
    ChatForkResponse — ``POST /chat/fork`` response schema.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from sevn.channels.webchat import WebChatConfig
from sevn.gateway.auth import mint_webchat_jwt
from sevn.gateway.session_manager import SessionManager
from sevn.ui.dashboard.api.deps import require_dashboard_csrf, require_dashboard_owner
from sevn.ui.dashboard.services.auth import DashboardClaims
from sevn.workspace.layout import WorkspaceLayout

router = APIRouter(prefix="/chat", tags=["dashboard-chat"])


class ChatTokenResponse(BaseModel):
    """Body for ``POST /chat/token`` — server-minted webchat JWT."""

    model_config = ConfigDict(extra="ignore")

    token: str
    expires_at: int
    expires_in: int
    session_id_hint: str


class ChatForkResponse(BaseModel):
    """Body for ``POST /chat/fork`` — rotated webchat session id."""

    model_config = ConfigDict(extra="ignore")

    session_id: str


def _owner_webchat_sub(claims: DashboardClaims) -> str:
    """Return the stable webchat ``sub`` for the dashboard owner.

    Args:
        claims (DashboardClaims): Verified dashboard JWT claims.

    Returns:
        str: Owner subject (always ``owner`` in v1).

    Examples:
        >>> from sevn.ui.dashboard.services.auth import DashboardClaims
        >>> _owner_webchat_sub(
        ...     DashboardClaims(
        ...         sub="owner",
        ...         aud="dashboard",
        ...         exp=0,
        ...         workspace=".",
        ...         scope=(),
        ...     ),
        ... )
        'owner'
    """

    return claims.sub


async def _ensure_owner_webchat_session(
    request: Request,
    *,
    sub: str,
) -> str:
    """Resolve or create the durable webchat session for ``webchat:{sub}``.

    Args:
        request (Request): FastAPI request with gateway session manager on app state.
        sub (str): Verified owner webchat subject.

    Returns:
        str: Gateway session id for the owner webchat scope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_ensure_owner_webchat_session)
        True
    """

    sessions: SessionManager = request.app.state.gateway_sessions
    scope_key = f"webchat:{sub}"
    return await sessions.ensure_session(
        scope_key=scope_key,
        channel="webchat",
        user_id=sub,
    )


@router.post("/token")
async def chat_token(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> ChatTokenResponse:
    """Mint a short-lived ``aud=webchat`` JWT for the verified dashboard owner.

    The server sets ``sub`` from the dashboard session — client-supplied identity
    is never honored (plan 014 / MC W6 contract).

    Args:
        request (Request): FastAPI request with webchat config on app state.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): CSRF gate (side effect only).

    Returns:
        ChatTokenResponse: Token bundle plus ``session_id_hint`` for resume UI.

    Raises:
        HTTPException: ``503`` when webchat JWT secret is not configured.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(chat_token)
        True
    """

    secret: str | None = request.app.state.webchat_jwt_secret
    if not secret:
        raise HTTPException(status_code=503, detail="webchat_jwt_secret_unconfigured")
    cfg: WebChatConfig = request.app.state.webchat_config
    sub = _owner_webchat_sub(_claims)
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        body = {}
    if isinstance(body, dict) and body.get("sub") is not None:
        raise HTTPException(status_code=400, detail="client_sub_not_allowed")
    token, expires_in = mint_webchat_jwt(
        secret=secret,
        sub=sub,
        ttl_seconds=int(cfg.jwt_ttl_seconds),
    )
    session_id = await _ensure_owner_webchat_session(request, sub=sub)
    now = int(time.time())
    return ChatTokenResponse(
        token=token,
        expires_at=now + expires_in,
        expires_in=expires_in,
        session_id_hint=session_id,
    )


@router.post("/fork")
async def chat_fork(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> ChatForkResponse:
    """Rotate the owner webchat session to start a fresh conversation.

    Cancels any in-flight turn on the prior session before minting a new id.

    Args:
        request (Request): FastAPI request with session manager and layout.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): CSRF gate (side effect only).

    Returns:
        ChatForkResponse: New gateway session id for the same owner scope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(chat_fork)
        True
    """

    sub = _owner_webchat_sub(_claims)
    sessions: SessionManager = request.app.state.gateway_sessions
    layout: WorkspaceLayout = request.app.state.layout
    prior = await _ensure_owner_webchat_session(request, sub=sub)
    await sessions.cancel_active_dispatch(prior)
    try:
        new_id = await sessions.rotate_session(prior, content_root=layout.content_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="session_not_found") from exc
    return ChatForkResponse(session_id=new_id)


__all__ = ["router"]
