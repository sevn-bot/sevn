"""Mission Control dashboard registration facade (`specs/24-dashboard.md` §4.1).

Module: sevn.ui.dashboard
Depends: fastapi, sevn.ui.dashboard.api, sevn.ui.dashboard.services, sevn.ui.dashboard.ws

Exports:
    register_dashboard_routes — register REST and WebSocket routes.
"""

from __future__ import annotations

from fastapi import FastAPI  # noqa: TC002

from sevn.agent.adapters.tool_approval_bridge import install_tool_approval_bridge
from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import WorkspaceConfig
from sevn.ui.dashboard.api import create_dashboard_api_router
from sevn.ui.dashboard.services import DashboardAuthService
from sevn.ui.dashboard.ws import DashboardHub, dashboard_ws_endpoint
from sevn.ui.dashboard.ws_terminal import dashboard_terminal_ws_endpoint
from sevn.ui.shared import register_shared_ui_routes


def register_dashboard_routes(
    app: FastAPI,
    settings: WorkspaceConfig | None,
    *,
    process_settings: ProcessSettings | None = None,
) -> None:
    """Register Mission Control REST and WebSocket routes on the gateway app.

    The Mission Control vanilla JS SPA is mounted separately by
    :func:`sevn.gateway.http_server._mount_mission_control_spa` from
    ``src/sevn/ui/spa/dashboard/`` (shared design tokens at ``/style/*``).

    Args:
        app (FastAPI): Existing gateway app instance.
        settings (WorkspaceConfig | None): Parsed workspace settings when known.
        process_settings (ProcessSettings | None): Env-derived settings.

    Returns:
        None: Routes and app-state services are installed in-place.

    Examples:
        >>> from fastapi import FastAPI
        >>> a = FastAPI()
        >>> register_dashboard_routes(a, None)
        >>> any(getattr(r, "path", "") == "/ws/dashboard" for r in a.routes)
        True
    """

    process = process_settings or ProcessSettings()
    app.state.dashboard_auth_service = DashboardAuthService(
        workspace=settings,
        process_settings=process,
    )
    hub = DashboardHub()
    app.state.dashboard_hub = hub
    install_tool_approval_bridge(app, hub=hub)
    app.include_router(create_dashboard_api_router())
    app.add_api_websocket_route("/ws/dashboard", dashboard_ws_endpoint)
    app.add_api_websocket_route("/ws/dashboard/terminal", dashboard_terminal_ws_endpoint)
    register_shared_ui_routes(app)

    _ = settings


# explanation: this is a facade for the dashboard routes
__all__ = ["register_dashboard_routes"]
