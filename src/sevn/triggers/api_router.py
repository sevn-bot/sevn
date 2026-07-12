"""HTTP API for non-interactive runs (`specs/30-non-interactive-triggers.md` §2.2).

Module: sevn.triggers.api_router
Depends: fastapi, pydantic

Exports:
    RunCreateBody — JSON body for ``POST /api/v1/run``.
    build_api_router — ``/api/v1/run`` + ``/api/v1/runs/{run_id}``.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from sevn.config.workspace_config import WorkspaceConfig
from sevn.triggers.auth import TRIGGERS_API_OPENAPI_BEARER_SCOPES, verify_triggers_api_bearer
from sevn.triggers.dispatcher import (
    agent_dispatch_kwargs,
    dispatch_notify_only,
    dispatch_run,
)
from sevn.triggers.hooks_protocol import TriggerPluginHookSurface
from sevn.triggers.request import DeliveryMode, DispatchRequest, ResultChannel, RoutingMode
from sevn.triggers.ws_topics import trigger_run_ws_topic


class RunCreateBody(BaseModel):
    """Request body for ``POST /api/v1/run``."""

    model_config = ConfigDict(extra="allow")

    prompt: str
    routing_mode: RoutingMode = "fixed"
    delivery_mode: DeliveryMode = "agent_pass"
    permission_template_ref: str = "default"
    allow_tier_cd: bool = False
    result_channel: ResultChannel = Field(default_factory=lambda: ResultChannel(kind="LOG"))
    correlation_id: str | None = None


def _resolved_gateway_token(request: Request) -> str | None:
    """Return gateway bearer resolved at boot (``app.state.resolved_gateway_token``).

    Args:
        request (Request): Active FastAPI request.

    Returns:
        str | None: Resolved bearer token when boot succeeded.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_resolved_gateway_token)
        True
    """
    token = getattr(request.app.state, "resolved_gateway_token", None)
    return str(token).strip() if token else None


async def _publish_run_event(request: Request, run_id: str, status: str) -> None:
    """Publish one run status transition on the dashboard WebSocket bus.

    Args:
        request (Request): Active FastAPI request (reads ``dashboard_hub``).
        run_id (str): Run / correlation identifier.
        status (str): Coarse status label for subscribers.

    Returns:
        None: Side-effect only.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_publish_run_event)
        True
    """
    hub = getattr(request.app.state, "dashboard_hub", None)
    if hub is None:
        return
    await hub.publish(
        trigger_run_ws_topic(run_id),
        {"run_id": run_id, "status": status},
    )


def _enforce_triggers_api_auth(request: Request) -> None:
    """Raise ``401`` when triggers API credentials are missing or invalid.

    Args:
        request (Request): Active FastAPI request.

    Raises:
        HTTPException: When auth is required and verification fails.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_enforce_triggers_api_auth)
        True
    """
    secret = getattr(request.app.state, "webchat_jwt_secret", None)
    webchat_secret = str(secret).strip() if isinstance(secret, str) and secret.strip() else None
    if not verify_triggers_api_bearer(
        authorization_header=request.headers.get("Authorization"),
        gateway_token=_resolved_gateway_token(request),
        webchat_jwt_secret=webchat_secret,
    ):
        raise HTTPException(status_code=401, detail="unauthorized")


def build_api_router() -> APIRouter:
    """Return the versioned HTTP API router for trigger runs.

    Routes read ``workspace``, ``layout``, ``gateway_trace``, ``trigger_dispatch_gate``,
    and optional ``trigger_plugin_hooks`` from ``request.app.state``.

    Returns:
        APIRouter: Mounted with ``POST /run`` and ``GET /runs/{run_id}`` under prefix ``/api/v1``.

    Examples:
        >>> from sevn.triggers.api_router import build_api_router
        >>> build_api_router().prefix
        '/api/v1'
    """
    router = APIRouter(prefix="/api/v1", tags=["triggers-api"])
    _run_security = [{"HTTPBearer": list(TRIGGERS_API_OPENAPI_BEARER_SCOPES)}]

    @router.post(
        "/run",
        openapi_extra={"security": _run_security},
        responses={202: {"description": "Run accepted for asynchronous dispatch"}},
    )
    async def create_run(body: RunCreateBody, request: Request) -> dict[str, str]:
        ws: WorkspaceConfig = request.app.state.workspace
        if ws.triggers and ws.triggers.paused:
            raise HTTPException(status_code=503, detail={"error": "triggers_paused"})

        _enforce_triggers_api_auth(request)

        gate = request.app.state.trigger_dispatch_gate
        await gate.acquire_api_slot()
        try:
            cid = body.correlation_id or str(uuid.uuid4())
            await _publish_run_event(request, cid, "accepted")
            hooks: TriggerPluginHookSurface | None = getattr(
                request.app.state,
                "trigger_plugin_hooks",
                None,
            )
            layout = request.app.state.layout
            trace = request.app.state.gateway_trace
            req = DispatchRequest(
                prompt=body.prompt,
                routing_mode=body.routing_mode,
                delivery_mode=body.delivery_mode,
                permission_template_ref=body.permission_template_ref,
                allow_tier_cd=body.allow_tier_cd,
                result_channel=body.result_channel,
                correlation_id=cid,
                trigger_meta={"transport": "api"},
                notify_template="{{ prompt }}" if body.delivery_mode == "notify_only" else None,
            )
            if body.delivery_mode == "notify_only":
                await dispatch_notify_only(
                    req,
                    workspace=ws,
                    content_root=layout.content_root,
                    trace=trace,
                    hooks=hooks,
                )
            else:
                await dispatch_run(
                    req,
                    workspace=ws,
                    content_root=layout.content_root,
                    trace=trace,
                    hooks=hooks,
                    **agent_dispatch_kwargs(getattr(request.app.state, "gateway_router", None)),
                )
            status: dict[str, Any] = request.app.state.trigger_run_status
            status[cid] = "completed"
            await _publish_run_event(request, cid, "completed")
        finally:
            gate.release_api_slot()

        return {"run_id": cid, "correlation_id": cid}

    @router.get(
        "/runs/{run_id}",
        openapi_extra={"security": _run_security},
    )
    async def get_run(run_id: str, request: Request) -> dict[str, object]:
        _enforce_triggers_api_auth(request)
        status_map: dict[str, Any] = request.app.state.trigger_run_status
        st = status_map.get(run_id, "unknown")
        return {"run_id": run_id, "status": st}

    return router
