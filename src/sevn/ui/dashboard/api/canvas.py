"""Dashboard OpenUI Canvas tab REST router (`specs/24-dashboard.md` §4.4).

Module: sevn.ui.dashboard.api.canvas
Depends: json, sqlite3, time, fastapi, sevn.ui.openui

Exports:
    dashboard_canvas — latest OpenUI iframe URL for the Canvas tab.
"""

from __future__ import annotations

import json
import sqlite3
import time

from fastapi import APIRouter, Depends, Request

from sevn.ui.dashboard.api.deps import require_dashboard_owner
from sevn.ui.dashboard.services.auth import DashboardClaims
from sevn.ui.openui.models import effective_openui_config
from sevn.ui.openui.tokens import sign_token

router = APIRouter(prefix="/dashboard", tags=["dashboard-canvas"])


def _safe_origin(request: Request) -> str:
    """Derive same-origin hint for sandboxed iframe embedding.

    Args:
        request (Request): Incoming HTTP request.

    Returns:
        str: ``scheme://host`` without trailing slash.

    Examples:
        >>> from starlette.requests import Request
        >>> scope = {
        ...     "type": "http",
        ...     "scheme": "http",
        ...     "server": ("127.0.0.1", 3001),
        ...     "path": "/",
        ...     "headers": [],
        ... }
        >>> _safe_origin(Request(scope))
        'http://127.0.0.1:3001'
    """

    base = str(request.base_url).rstrip("/")
    return base  # noqa: RET504


def _title_from_extra(raw: str | None) -> str:
    """Parse optional title from ``openui_tokens.extra_json``.

    Args:
        raw (str | None): Serialized JSON blob.

    Returns:
        str: Title string or empty.

    Examples:
        >>> _title_from_extra('{"title": "Report"}')
        'Report'
        >>> _title_from_extra(None)
        ''
    """

    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    title = parsed.get("title")
    return title.strip() if isinstance(title, str) else ""


@router.get("/canvas")
async def dashboard_canvas(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return the latest live OpenUI iframe URL for the Canvas tab.

    Args:
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: ``iframe_src``, ``safe_origin``, ``title``, and empty-state flags.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(dashboard_canvas)
        True
    """

    _ = _claims
    safe_origin = _safe_origin(request)
    secret = str(getattr(request.app.state, "openui_secret", "") or "")
    if not secret:
        return {
            "configured": False,
            "empty": True,
            "iframe_src": "",
            "safe_origin": safe_origin,
            "title": "",
            "record_id": "",
            "channel": "",
        }

    conn: sqlite3.Connection = request.app.state.sqlite_conn
    now_ns = time.time_ns()
    row = conn.execute(
        """
        SELECT record_id, workspace_id, session_id, message_id, channel, extra_json
        FROM openui_tokens
        WHERE expires_at_ns >= ?
        ORDER BY expires_at_ns DESC
        LIMIT 1
        """,
        (now_ns,),
    ).fetchone()
    if row is None:
        return {
            "configured": True,
            "empty": True,
            "iframe_src": "",
            "safe_origin": safe_origin,
            "title": "",
            "record_id": "",
            "channel": "",
        }

    record_id, workspace_id, session_id, message_id, channel, extra_json = row
    ws = request.app.state.workspace
    ou_cfg = effective_openui_config(getattr(ws, "openui", None))
    exp_unix = int(time.time()) + int(ou_cfg.token_ttl_seconds)
    render_tok = sign_token(
        secret=secret,
        workspace_id=str(workspace_id or "."),
        session_id=str(session_id),
        message_id=str(message_id),
        record_id=str(record_id),
        scope="render",
        exp_unix=exp_unix,
    )
    iframe_src = f"/openui/{render_tok}"
    title = _title_from_extra(extra_json if isinstance(extra_json, str) else None)
    return {
        "configured": True,
        "empty": False,
        "iframe_src": iframe_src,
        "safe_origin": safe_origin,
        "title": title or "OpenUI canvas",
        "record_id": str(record_id),
        "channel": str(channel or ""),
    }


__all__ = ["dashboard_canvas"]
