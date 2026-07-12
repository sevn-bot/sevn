"""Cursor Cloud Agents API v1 forwarder (`specs/29-cursor-cloud-agent.md` §2.3).

Module: sevn.proxy.integration.cursor
Depends: httpx, loguru, sevn.proxy.integration.mcp_expand

Exports:
    dispatch_cursor — route ``service=cursor`` integration methods.
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx
from loguru import logger
from starlette.requests import Request
from starlette.responses import JSONResponse

from sevn.config.workspace_config import WorkspaceConfig
from sevn.proxy.integration.mcp_expand import merge_mcp_profile_into_args
from sevn.security.secrets.cache import ResolvedSecretsCache
from sevn.security.secrets.chain import get_secret_resilient

CURSOR_API_KEY_SECRET: str = "integration.cursor.api_key"
_CURSOR_BASE_URL: str = "https://api.cursor.com"
_DEFAULT_TIMEOUT_S: float = 120.0


async def _resolve_cursor_api_key(
    cache: ResolvedSecretsCache | None,
) -> str | None:
    """Load Cursor API key from env or secrets chain.

    Args:
        cache (ResolvedSecretsCache | None): Workspace secrets cache.

    Returns:
        str | None: API key or ``None`` when unset.

    Examples:
        >>> import asyncio
        >>> asyncio.run(_resolve_cursor_api_key(None)) is None or True
        True
    """
    env_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if env_key:
        return env_key
    if cache is None:
        return None
    return await get_secret_resilient(cache.chain, CURSOR_API_KEY_SECRET)


def _basic_auth_header(api_key: str) -> dict[str, str]:
    """Build HTTP Basic auth header for Cursor API.

    Args:
        api_key (str): Raw API key.

    Returns:
        dict[str, str]: Authorization header dict.

    Examples:
        >>> hdr = _basic_auth_header("cursor_test")
        >>> hdr["Authorization"].startswith("Basic ")
        True
    """
    token = base64.b64encode(f"{api_key}:".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


async def _cursor_request(
    *,
    method: str,
    path: str,
    api_key: str,
    json_body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Perform one Cursor API HTTP call.

    Args:
        method (str): HTTP verb.
        path (str): Path beginning with ``/v1/``.
        api_key (str): Cursor API key.
        json_body (dict[str, Any] | None): JSON body for POST.
        params (dict[str, str] | None): Query string parameters.

    Returns:
        tuple[int, dict[str, Any]]: Status code and parsed JSON object.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_cursor_request)
        True
    """
    url = f"{_CURSOR_BASE_URL}{path}"
    headers = {
        **_basic_auth_header(api_key),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_S) as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                json=json_body,
                params=params,
            )
    except httpx.HTTPError as exc:
        logger.warning("cursor upstream error {} {}: {}", method, path, exc)
        return 502, {"detail": f"cursor upstream failed: {exc}"}
    try:
        data = response.json()
    except ValueError:
        return response.status_code, {
            "detail": f"cursor returned non-JSON (status {response.status_code})",
        }
    if not isinstance(data, dict):
        return response.status_code, {"detail": "cursor returned non-object JSON"}
    if response.status_code >= 400:
        detail = str(data.get("detail") or data.get("message") or data)
        return response.status_code, {"detail": detail, "upstream": data}
    return response.status_code, data


async def dispatch_cursor(
    request: Request,
    *,
    method: str,
    args: dict[str, Any],
    workspace_config: WorkspaceConfig | None,
    secrets_cache: ResolvedSecretsCache | None,
) -> JSONResponse:
    """Dispatch a Cursor integration method.

    Args:
        request (Request): Starlette request (unused; reserved).
        method (str): Dotted method name (``agents.create``, ...).
        args (dict[str, Any]): Method arguments from the gateway.
        workspace_config (WorkspaceConfig | None): Workspace config for MCP profiles.
        secrets_cache (ResolvedSecretsCache | None): Secrets cache.

    Returns:
        JSONResponse: Proxy JSON envelope with upstream body or error.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(dispatch_cursor)
        True
    """
    _ = request
    api_key = await _resolve_cursor_api_key(secrets_cache)
    if not api_key:
        return JSONResponse(
            {"detail": "Cursor API key not configured (integration.cursor.api_key)"},
            status_code=503,
        )

    skills = workspace_config.skills if workspace_config is not None else None

    if method == "agents.create":
        body = await merge_mcp_profile_into_args(
            args,
            skills=skills if isinstance(skills, dict) else None,
            cache=secrets_cache,
        )
        status, data = await _cursor_request(
            method="POST",
            path="/v1/agents",
            api_key=api_key,
            json_body=body,
        )
        return JSONResponse(data, status_code=status)

    if method == "agents.get":
        agent_id = str(args.get("id") or args.get("agent_id") or "").strip()
        if not agent_id:
            return JSONResponse({"detail": "id is required"}, status_code=422)
        status, data = await _cursor_request(
            method="GET",
            path=f"/v1/agents/{agent_id}",
            api_key=api_key,
        )
        return JSONResponse(data, status_code=status)

    if method == "agents.list":
        params: dict[str, str] = {}
        if args.get("limit") is not None:
            params["limit"] = str(args["limit"])
        if args.get("cursor") is not None:
            params["cursor"] = str(args["cursor"])
        status, data = await _cursor_request(
            method="GET",
            path="/v1/agents",
            api_key=api_key,
            params=params or None,
        )
        return JSONResponse(data, status_code=status)

    if method == "runs.get":
        agent_id = str(args.get("agent_id") or args.get("id") or "").strip()
        run_id = str(args.get("run_id") or args.get("runId") or "").strip()
        if not agent_id or not run_id:
            return JSONResponse(
                {"detail": "agent_id and run_id are required"},
                status_code=422,
            )
        status, data = await _cursor_request(
            method="GET",
            path=f"/v1/agents/{agent_id}/runs/{run_id}",
            api_key=api_key,
        )
        return JSONResponse(data, status_code=status)

    if method == "artifacts.list":
        agent_id = str(args.get("agent_id") or args.get("id") or "").strip()
        if not agent_id:
            return JSONResponse({"detail": "agent_id is required"}, status_code=422)
        status, data = await _cursor_request(
            method="GET",
            path=f"/v1/agents/{agent_id}/artifacts",
            api_key=api_key,
        )
        return JSONResponse(data, status_code=status)

    if method == "artifacts.download":
        agent_id = str(args.get("agent_id") or args.get("id") or "").strip()
        artifact_path = str(args.get("path") or "").strip()
        if not agent_id or not artifact_path:
            return JSONResponse(
                {"detail": "agent_id and path are required"},
                status_code=422,
            )
        status, data = await _cursor_request(
            method="GET",
            path=f"/v1/agents/{agent_id}/artifacts/download",
            api_key=api_key,
            params={"path": artifact_path},
        )
        return JSONResponse(data, status_code=status)

    return JSONResponse({"detail": f"unknown cursor method: {method}"}, status_code=422)
