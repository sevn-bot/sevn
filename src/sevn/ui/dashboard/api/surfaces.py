"""Mission Control Surfaces group REST router (`specs/24-dashboard.md` MC-11).

Module: sevn.ui.dashboard.api.surfaces
Depends: pathlib, fastapi, sevn.config.workspace_config, sevn.gateway.menu, sevn.gateway.webapp_qa,
    sevn.onboarding.draft_store, sevn.ui.dashboard.api.deps

Exports:
    telegram_menu_overview — live ``/config`` snapshot + docs catalog link.
    telegram_menu_put — persist Telegram menu-display toggles to ``sevn.json``.
    web_apps_overview — ``/webapp/*`` route inventory and HTTPS gating hints.
    web_apps_put — persist webchat Web-App settings to ``sevn.json``.
    onboarding_overview — wizard URL, draft state, last onboard log summary.
    users_rbac_overview — v1 owner-only auth model (real panel payload).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from sevn.config.workspace_config import ChannelsWorkspaceSectionConfig, WorkspaceConfig
from sevn.gateway.menu import (
    _CONFIG_ROOT_TILES,
    build_config_menu_keyboard,
    web_ui_url_from_workspace,
)
from sevn.gateway.webapp_qa import resolve_webapp_public_base, webapp_inline_buttons_allowed
from sevn.onboarding.draft_store import draft_path, read_draft
from sevn.ui.dashboard.api._config_persist import (
    config_error,
    config_validation_error,
    deep_merge,
    load_workspace_document,
    persist_workspace_document,
    read_config_body,
)
from sevn.ui.dashboard.api.deps import require_dashboard_csrf, require_dashboard_owner
from sevn.ui.dashboard.services.auth import DashboardClaims, local_open_effective
from sevn.workspace.layout import WorkspaceLayout

router = APIRouter(prefix="/surfaces", tags=["dashboard-surfaces"])

_TELEGRAM_MENU_DOCS_URL = "https://sevn.bot/telegram-menu.html"
_NAV_SKIP_TEXT = frozenset({"◀ Back", "🏠 Home", "❌ Close"})


def _collect_live_telegram_menu(workspace: WorkspaceConfig) -> list[dict[str, Any]]:
    """Snapshot live ``/config`` section keyboards for the dashboard panel.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        list[dict[str, Any]]: Section rows with action button metadata.

    Examples:
        >>> rows = _collect_live_telegram_menu(WorkspaceConfig.minimal())
        >>> any(r["section_id"] == "session" for r in rows)
        True
    """

    sections: list[dict[str, Any]] = []
    for tile_label, section_id, section_cb in _CONFIG_ROOT_TILES:
        kb = build_config_menu_keyboard(workspace, section=section_id)  # type: ignore[arg-type]
        buttons: list[dict[str, str]] = []
        for row in kb.get("inline_keyboard", []):
            for btn in row:
                text = str(btn.get("text", ""))
                cb = btn.get("callback_data")
                if not text or not isinstance(cb, str):
                    continue
                if cb.startswith(("cfg:nav:", "cfg:section:help")):
                    continue
                if text in _NAV_SKIP_TEXT:
                    continue
                clean = text.lstrip("🚧📋🔒 ").strip()
                buttons.append({"label": clean, "callback_data": cb})
        sections.append(
            {
                "section_id": section_id,
                "tile_label": tile_label,
                "section_callback": section_cb,
                "buttons": buttons,
            },
        )
    return sections


def _latest_onboard_log(logs_dir: Path) -> dict[str, Any] | None:
    """Return metadata for the newest ``onboard-*.log`` under the workspace logs dir.

    Args:
        logs_dir (Path): ``<workspace>/logs`` directory.

    Returns:
        dict[str, Any] | None: Filename, mtime, and byte size when a log exists.

    Examples:
        >>> _latest_onboard_log(Path("/nonexistent")) is None
        True
    """

    if not logs_dir.is_dir():
        return None
    candidates = sorted(
        logs_dir.glob("onboard-*.log"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not candidates:
        return None
    latest = candidates[0]
    stat = latest.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
    return {
        "filename": latest.name,
        "path": str(latest),
        "size_bytes": stat.st_size,
        "modified_at": mtime,
    }


def _gateway_onboarding_wizard_url(request: Request) -> str | None:
    """Build a gateway-mounted onboarding wizard URL when a token is available.

    Args:
        request (Request): Active HTTP request (for host/scheme).

    Returns:
        str | None: Absolute wizard URL with ``onboard_token``, or ``None``.

    Examples:
        >>> _gateway_onboarding_wizard_url.__name__
        '_gateway_onboarding_wizard_url'
    """

    token = str(getattr(request.app.state, "gateway_onboarding_token", "") or "").strip()
    if not token:
        token = os.environ.get("SEVN_GATEWAY_ONBOARD_TOKEN", "").strip()
    if not token:
        return None
    base = str(request.base_url).rstrip("/")
    return f"{base}/onboarding/?onboard_token={token}"


@router.get("/telegram-menu")
async def telegram_menu_overview(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, Any]:
    """Live Telegram ``/config`` menu snapshot plus public docs catalog link.

    Args:
        request (Request): Incoming HTTP request.
        _claims (DashboardClaims): Verified owner claims.

    Returns:
        dict[str, Any]: Docs URL, Mission Control tab path, and section snapshot.

    Examples:
        >>> telegram_menu_overview.__name__
        'telegram_menu_overview'
    """

    workspace: WorkspaceConfig = request.app.state.workspace
    mc_base = web_ui_url_from_workspace(workspace)
    mc_tab_path = "/mission/telegram-menu"
    return {
        "docs_url": _TELEGRAM_MENU_DOCS_URL,
        "mission_control_tab_path": mc_tab_path,
        "mission_control_url": f"{mc_base.rstrip('/')}{mc_tab_path}" if mc_base else None,
        "sections": _collect_live_telegram_menu(workspace),
        "section_count": len(_CONFIG_ROOT_TILES),
        "editable": _telegram_menu_editable(workspace),
    }


@router.get("/web-apps")
async def web_apps_overview(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, Any]:
    """Inventory Telegram Web App routes mounted on the gateway.

    Args:
        request (Request): Incoming HTTP request.
        _claims (DashboardClaims): Verified owner claims.

    Returns:
        dict[str, Any]: Route list with availability hints.

    Examples:
        >>> web_apps_overview.__name__
        'web_apps_overview'
    """

    workspace: WorkspaceConfig = request.app.state.workspace
    public_base = resolve_webapp_public_base(workspace)
    https_ok = webapp_inline_buttons_allowed(public_base)
    routes = [
        {
            "method": "GET",
            "path": "/webapp/",
            "description": "Webchat shell (JWT session)",
            "status": "mounted",
        },
        {
            "method": "GET",
            "path": "/webapp/share",
            "description": "Share Web App (token query)",
            "status": "mounted" if https_ok else "requires_https",
        },
        {
            "method": "POST",
            "path": "/webapp/share/payload",
            "description": "Share payload (initData verify)",
            "status": "mounted" if https_ok else "requires_https",
        },
        {
            "method": "GET",
            "path": "/webapp/feedback",
            "description": "Feedback Web App (token query)",
            "status": "mounted" if https_ok else "requires_https",
        },
        {
            "method": "POST",
            "path": "/webapp/feedback/submit",
            "description": "Feedback submit (initData verify)",
            "status": "mounted" if https_ok else "requires_https",
        },
        {
            "method": "POST",
            "path": "/webapp/telegram",
            "description": "Telegram initData verify for webchat",
            "status": "mounted",
        },
    ]
    return {
        "public_base": public_base,
        "inline_buttons_allowed": https_ok,
        "routes": routes,
        "editable": _web_apps_editable(workspace),
    }


@router.get("/onboarding")
async def onboarding_overview(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, Any]:
    """Onboarding wizard entry points and last-run summary from workspace artifacts.

    Args:
        request (Request): Incoming HTTP request.
        _claims (DashboardClaims): Verified owner claims.

    Returns:
        dict[str, Any]: CLI hint, gateway wizard URL, draft/log/profile summary.

    Examples:
        >>> onboarding_overview.__name__
        'onboarding_overview'
    """

    workspace: WorkspaceConfig = request.app.state.workspace
    layout: WorkspaceLayout = request.app.state.layout
    sevn_json = layout.sevn_json_path
    draft_file = draft_path(sevn_json)
    draft_present = draft_file.is_file()
    draft_keys: list[str] = []
    if draft_present:
        try:
            body = read_draft(sevn_json)
            if isinstance(body, dict):
                draft_keys = sorted(body.keys())[:12]
        except (OSError, ValueError):
            draft_present = False

    applied_profile: str | None = None
    if workspace.onboarding is not None:
        applied_profile = workspace.onboarding.applied_profile

    logs_dir = layout.content_root / "logs"
    last_log = _latest_onboard_log(logs_dir)

    return {
        "cli_command": "sevn onboard --web",
        "gateway_wizard_url": _gateway_onboarding_wizard_url(request),
        "draft_present": draft_present,
        "draft_top_level_keys": draft_keys,
        "applied_profile": applied_profile,
        "last_log": last_log,
        "mission_control_tab_path": "/mission/onboarding",
    }


@router.get("/users-rbac")
async def users_rbac_overview(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, Any]:
    """v1 owner-only authentication model for the Users & RBAC tab.

    Args:
        request (Request): Incoming HTTP request.
        _claims (DashboardClaims): Verified owner claims.

    Returns:
        dict[str, Any]: Auth mode, capabilities, and post-v1 multi-user notice.

    Examples:
        >>> users_rbac_overview.__name__
        'users_rbac_overview'
    """

    workspace: WorkspaceConfig = request.app.state.workspace
    dash = workspace.dashboard
    local_open = local_open_effective(workspace, request)
    tunnel_mode = "none"
    infra = workspace.model_extra or {}
    infra_block = infra.get("infrastructure")
    if isinstance(infra_block, dict):
        tunnel = infra_block.get("tunnel")
        if isinstance(tunnel, dict):
            raw = tunnel.get("mode")
            if isinstance(raw, str):
                tunnel_mode = raw

    return {
        "model": "owner_only_v1",
        "local_open_effective": local_open,
        "local_open_configured": bool(dash and dash.local_open),
        "tunnel_mode": tunnel_mode,
        "auth_required_remote": not local_open,
        "capabilities": [
            "Single workspace owner; no user table or viewer role in v1.",
            "Loopback sessions may use synthetic owner claims when local_open is effective.",
            "Tunneled or public dashboard URLs require dashboard.login_password + JWT.",
            "Mutating /api/v1 routes use CSRF double-submit (cookie + X-CSRF-Token).",
            "Webchat JWT (aud=webchat) is minted from the same owner session when embedded.",
        ],
        "not_in_v1": [
            "Multi-user teams, SSO, or read-only viewer roles.",
            "Per-tab RBAC matrices or delegated admin accounts.",
        ],
        "spec_refs": ["specs/24-dashboard.md §2.2", "prd/07-mission-control.md §5.1"],
        "mission_control_tab_path": "/mission/users-rbac",
    }


def _telegram_menu_editable(workspace: WorkspaceConfig) -> dict[str, Any]:
    """Project the editable Telegram menu-display toggles.

    Args:
        workspace (WorkspaceConfig): Active workspace config.

    Returns:
        dict[str, Any]: Reply-keyboard, quick-action, and routing toggles.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_telegram_menu_editable)
        True
    """

    channels = workspace.channels
    telegram = channels.telegram if channels else None
    reply_kb = telegram.reply_keyboard if telegram else None
    quick = telegram.quick_actions if telegram else None
    return {
        "reply_keyboard_enabled": reply_kb.enabled if reply_kb else None,
        "show_routing": telegram.show_routing if telegram else None,
        "quick_actions": (quick.model_dump(mode="python", exclude_none=True) if quick else {}),
    }


def _web_apps_editable(workspace: WorkspaceConfig) -> dict[str, Any]:
    """Project the editable webchat settings that gate the Web Apps surface.

    Args:
        workspace (WorkspaceConfig): Active workspace config.

    Returns:
        dict[str, Any]: ``public``, ``allowed_origins``, and ``tts_inline``.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_web_apps_editable)
        True
    """

    channels = workspace.channels
    webchat = channels.webchat if channels else None
    return {
        "public": webchat.public if webchat else None,
        "allowed_origins": list(webchat.allowed_origins) if webchat else [],
        "tts_inline": webchat.tts_inline if webchat else None,
    }


def _persist_channels_patch(request: Request, patch: dict[str, Any]) -> WorkspaceConfig:
    """Deep-merge a ``channels`` patch into ``sevn.json`` and reload.

    Args:
        request (Request): FastAPI request with workspace layout.
        patch (dict[str, Any]): Partial ``channels`` subtree override.

    Returns:
        WorkspaceConfig: Reloaded config after validation and promotion.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_persist_channels_patch)
        True
    """

    on_disk = load_workspace_document(request)
    merged = deep_merge(dict(on_disk.get("channels") or {}), patch)
    validated = ChannelsWorkspaceSectionConfig.model_validate(merged)
    on_disk["channels"] = validated.model_dump(mode="python", exclude_none=True)
    return persist_workspace_document(request, on_disk)


@router.put("/telegram-menu")
async def telegram_menu_put(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Persist Telegram menu-display toggles under ``channels.telegram``.

    Args:
        request (Request): JSON body with a ``telegram`` object.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: Updated editable projection, ``400``/``422`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(telegram_menu_put)
        True
    """

    body = await read_config_body(request)
    patch = body.get("telegram")
    if not isinstance(patch, dict):
        return config_error("invalid_body", "body.telegram must be a JSON object", status_code=400)
    try:
        ws = _persist_channels_patch(request, {"telegram": patch})
    except (ValidationError, ValueError, OSError) as exc:
        return config_validation_error(exc)
    return JSONResponse(status_code=200, content={"editable": _telegram_menu_editable(ws)})


@router.put("/web-apps")
async def web_apps_put(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Persist webchat Web-App settings under ``channels.webchat``.

    Args:
        request (Request): JSON body with a ``webchat`` object.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: Updated editable projection, ``400``/``422`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(web_apps_put)
        True
    """

    body = await read_config_body(request)
    patch = body.get("webchat")
    if not isinstance(patch, dict):
        return config_error("invalid_body", "body.webchat must be a JSON object", status_code=400)
    try:
        ws = _persist_channels_patch(request, {"webchat": patch})
    except (ValidationError, ValueError, OSError) as exc:
        return config_validation_error(exc)
    return JSONResponse(status_code=200, content={"editable": _web_apps_editable(ws)})


__all__ = [
    "onboarding_overview",
    "router",
    "telegram_menu_overview",
    "telegram_menu_put",
    "users_rbac_overview",
    "web_apps_overview",
    "web_apps_put",
]
