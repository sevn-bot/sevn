"""``POST /integration`` dispatcher for egress proxy (`specs/29-cursor-cloud-agent.md`).

Module: sevn.proxy.integration.router
Depends: starlette, sevn.proxy.integration.cursor

Exports:
    integration_post — ASGI handler.
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from sevn.config.workspace_config import WorkspaceConfig
from sevn.proxy.integration.cursor import dispatch_cursor
from sevn.proxy.integration.github import dispatch_github
from sevn.security.secrets.cache import ResolvedSecretsCache


async def integration_post(request: Request) -> JSONResponse:
    """Dispatch ``{service, method, args}`` to a configured integration forwarder.

    Args:
        request (Request): Starlette request with JSON body.

    Returns:
        JSONResponse: Upstream JSON or validation error.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(integration_post)
        True
    """
    try:
        body: Any = await request.json()
    except Exception:
        return JSONResponse({"detail": "invalid JSON body"}, status_code=422)
    if not isinstance(body, dict):
        return JSONResponse({"detail": "body must be a JSON object"}, status_code=422)

    service = str(body.get("service") or "").strip()
    method = str(body.get("method") or "").strip()
    args = body.get("args")
    if not service or not method:
        return JSONResponse(
            {"detail": "service and method are required"},
            status_code=422,
        )
    if not isinstance(args, dict):
        args = {}

    ws_cfg = getattr(request.app.state, "workspace_config", None)
    workspace_config = ws_cfg if isinstance(ws_cfg, WorkspaceConfig) else None
    cache = getattr(request.app.state, "secrets_cache", None)
    secrets_cache = cache if isinstance(cache, ResolvedSecretsCache) else None

    if service == "cursor":
        return await dispatch_cursor(
            request,
            method=method,
            args=args,
            workspace_config=workspace_config,
            secrets_cache=secrets_cache,
        )

    if service == "github":
        return await dispatch_github(
            request,
            method=method,
            args=args,
            secrets_cache=secrets_cache,
        )

    return JSONResponse(
        {"detail": f"unknown integration service: {service}"},
        status_code=422,
    )
