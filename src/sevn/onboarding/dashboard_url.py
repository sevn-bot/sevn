"""Mission Control ``web_ui.url`` helper for onboarding promote (`specs/24-dashboard.md` MC-13).

Module: sevn.onboarding.dashboard_url
Depends: sevn.config.defaults, sevn.config.workspace_config

Exports:
    apply_web_ui_url_for_dashboard — set ``web_ui.url`` from gateway host/port when MC is on.
    mission_control_entry_url — ``{origin}/mission/`` for CLI and docs.
"""

from __future__ import annotations

from typing import Any

from sevn.config.defaults import DEFAULT_GATEWAY_HOST, DEFAULT_GATEWAY_PORT
from sevn.config.workspace_config import WorkspaceConfig, parse_workspace_config


def _gateway_origin_from_doc(doc: dict[str, Any]) -> str:
    """Build ``http://host:port`` from a workspace document gateway section.

    Args:
        doc (dict[str, Any]): Workspace JSON document.

    Returns:
        str: Gateway origin without trailing slash.

    Examples:
        >>> _gateway_origin_from_doc({"gateway": {"host": "127.0.0.1", "port": 3001}})
        'http://127.0.0.1:3001'
    """
    gw = doc.get("gateway")
    if not isinstance(gw, dict):
        gw = {}
    host = gw.get("host")
    if not isinstance(host, str) or not host.strip():
        host = DEFAULT_GATEWAY_HOST
    port_raw = gw.get("port")
    port = int(port_raw) if port_raw is not None else DEFAULT_GATEWAY_PORT
    return f"http://{host.strip()}:{port}".rstrip("/")


def apply_web_ui_url_for_dashboard(doc: dict[str, Any]) -> None:
    """Set ``web_ui.url`` when ``dashboard.enabled`` is true and URL is unset.

    Args:
        doc (dict[str, Any]): Merged workspace document in place (mutated).

    Examples:
        >>> d = {
        ...     "schema_version": 1,
        ...     "dashboard": {"enabled": True},
        ...     "gateway": {"port": 3002, "token": "${SECRET:keychain:sevn.gateway.token}"},
        ... }
        >>> apply_web_ui_url_for_dashboard(d)
        >>> d["web_ui"]["url"]
        'http://127.0.0.1:3002'
    """
    try:
        cfg = parse_workspace_config(doc)
    except (ValueError, TypeError):
        return
    if cfg.dashboard is None or not cfg.dashboard.enabled:
        return
    web_ui = doc.get("web_ui")
    if isinstance(web_ui, dict):
        existing = web_ui.get("url")
        if isinstance(existing, str) and existing.strip():
            return
    origin = _gateway_origin_from_doc(doc)
    doc.setdefault("web_ui", {})["url"] = origin


def mission_control_entry_url(workspace: WorkspaceConfig) -> str:
    """Return the Mission Control SPA entry URL for a parsed workspace.

    Args:
        workspace (WorkspaceConfig): Parsed ``sevn.json``.

    Returns:
        str: ``{gateway_origin}/mission/`` with trailing slash.

    Examples:
        >>> mission_control_entry_url(WorkspaceConfig.minimal())
        'http://127.0.0.1:3001/mission/'
    """
    doc: dict[str, Any] = {"gateway": {}}
    if workspace.gateway is not None:
        if workspace.gateway.host:
            doc["gateway"]["host"] = workspace.gateway.host
        if workspace.gateway.port is not None:
            doc["gateway"]["port"] = workspace.gateway.port
    return f"{_gateway_origin_from_doc(doc)}/mission/"


__all__ = [
    "apply_web_ui_url_for_dashboard",
    "mission_control_entry_url",
]
