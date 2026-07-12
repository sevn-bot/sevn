"""Mission Control sandbox web terminal REST API (MC W8).

Module: sevn.ui.dashboard.api.terminal
Depends: time, fastapi, pydantic, sevn.ui.dashboard.api.deps

Exports:
    TerminalSessionResponse — ``POST /terminal/session`` body.
    terminal_session — mint owner upgrade ticket before WS attach.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from sevn.config.defaults import SANDBOX_MAX_LIFETIME_S
from sevn.config.workspace_config import WorkspaceConfig
from sevn.ui.dashboard.api.deps import require_dashboard_csrf, require_dashboard_owner
from sevn.ui.dashboard.services.auth import DashboardClaims
from sevn.ui.dashboard.services.terminal_registry import terminal_session_registry

router = APIRouter(prefix="/terminal", tags=["dashboard-terminal"])

_UPGRADE_TTL_S = 120.0


def _terminal_max_lifetime_s(cfg: WorkspaceConfig) -> int:
    """Return configured sandbox max lifetime seconds for terminal sessions.

    Args:
        cfg (WorkspaceConfig): Parsed workspace config.

    Returns:
        int: Session hard timeout in seconds.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _terminal_max_lifetime_s(WorkspaceConfig.minimal()) == 7200
        True
    """
    sb = cfg.sandbox
    if sb and sb.max_lifetime is not None:
        return int(sb.max_lifetime)
    return int(SANDBOX_MAX_LIFETIME_S)


class TerminalSessionResponse(BaseModel):
    """Body for ``POST /terminal/session`` — WS upgrade ticket."""

    model_config = ConfigDict(extra="ignore")

    session_id: str
    expires_at: int
    max_lifetime_s: int
    ws_path: str


@router.post("/session")
async def terminal_session(
    request: Request,
    claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> TerminalSessionResponse:
    """Mint a one-shot terminal upgrade ticket (owner + CSRF) before WebSocket attach.

    Args:
        request (Request): FastAPI request with workspace on ``app.state``.
        claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): CSRF gate (side effect only).

    Returns:
        TerminalSessionResponse: Ticket consumed by ``/ws/dashboard/terminal``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(terminal_session)
        True
    """
    workspace = request.app.state.workspace
    max_lifetime = _terminal_max_lifetime_s(workspace)
    ticket = terminal_session_registry.mint(owner_sub=claims.sub, ttl_s=_UPGRADE_TTL_S)
    now = int(time.time())
    return TerminalSessionResponse(
        session_id=ticket.session_id,
        expires_at=int(now + _UPGRADE_TTL_S),
        max_lifetime_s=max_lifetime,
        ws_path="/ws/dashboard/terminal",
    )


__all__ = ["router"]
