"""Mission Control REST API router assembly.

Module: sevn.ui.dashboard.api
Depends: fastapi, sevn.ui.dashboard.api.auth, sevn.ui.dashboard.api.runs, sevn.ui.dashboard.api.sessions, sevn.ui.dashboard.api.system, sevn.ui.dashboard.api.traces

Exports:
    create_dashboard_api_router — assemble ``/api/v1`` dashboard routers.
"""

from __future__ import annotations

from fastapi import APIRouter

from sevn.ui.dashboard.api import (
    agent,
    audit,
    auth,
    canvas,
    channels,
    chat,
    cli_console,
    coding_agents,
    evolution,
    files,
    knowledge,
    nav,
    ops,
    ops_control,
    runs,
    search,
    secrets_store,
    self_improve,
    sessions,
    spec_kit,
    surfaces,
    system,
    terminal,
    tool_approvals,
    traces,
)


def create_dashboard_api_router() -> APIRouter:
    """Assemble the dashboard JSON API under ``/api/v1``.

    Returns:
        APIRouter: Router containing auth + protected Mission Control routes.

    Examples:
        >>> create_dashboard_api_router().prefix
        '/api/v1'
    """

    router = APIRouter(prefix="/api/v1")
    router.include_router(auth.router)
    router.include_router(nav.router)
    router.include_router(canvas.router)
    router.include_router(chat.router)
    router.include_router(search.router)
    router.include_router(audit.router)
    router.include_router(sessions.router)
    router.include_router(traces.router)
    router.include_router(self_improve.router)
    router.include_router(evolution.router)
    router.include_router(spec_kit.router)
    router.include_router(runs.router)
    router.include_router(channels.router)
    router.include_router(channels.alerts_router)
    router.include_router(system.router)
    router.include_router(ops.router)
    router.include_router(ops_control.router)
    router.include_router(knowledge.router)
    router.include_router(files.router)
    router.include_router(secrets_store.router)
    router.include_router(cli_console.router)
    router.include_router(terminal.router)
    router.include_router(agent.router)
    router.include_router(coding_agents.router)
    router.include_router(tool_approvals.router)
    router.include_router(surfaces.router)
    return router


__all__ = ["create_dashboard_api_router"]
