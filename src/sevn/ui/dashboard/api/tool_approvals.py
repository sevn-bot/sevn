"""Mission Control live tier-B tool approval API (MC W7).

Module: sevn.ui.dashboard.api.tool_approvals
Depends: fastapi, pydantic, sevn.agent.adapters.tool_approval_bridge, sevn.ui.dashboard.api.deps

Exports:
    tool_approvals_pending — list in-flight approval decisions.
    tool_approval_decide — submit once/session/always/deny verdict.
    ToolApprovalVerdictBody — POST body schema.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from sevn.agent.adapters.tool_approval_bridge import ApprovalVerdict, ToolApprovalBridge
from sevn.ui.dashboard.api._config_persist import (
    config_validation_error,
    load_workspace_document,
    persist_workspace_document,
)
from sevn.ui.dashboard.api.deps import require_dashboard_csrf, require_dashboard_owner
from sevn.ui.dashboard.services.auth import DashboardClaims
from sevn.ui.dashboard.services.mission_audit import emit_mission_audit

router = APIRouter(prefix="/agent", tags=["dashboard-agent-approvals"])


class ToolApprovalVerdictBody(BaseModel):
    """``POST /agent/approvals/{decision_id}`` request body."""

    verdict: Literal["once", "session", "always", "deny"] = Field(
        description="Operator approval scope or deny.",
    )


def _bridge(request: Request) -> ToolApprovalBridge | None:
    """Return the gateway tool approval bridge from app state.

    Args:
        request (Request): Active HTTP request.

    Returns:
        ToolApprovalBridge | None: Bridge when dashboard is registered.

    Examples:
        >>> import inspect
        >>> "request" in inspect.signature(_bridge).parameters
        True
    """

    return getattr(request.app.state, "tool_approval_bridge", None)


def _persist_always_preapproved(request: Request, tool_name: str) -> None:
    """Append ``tool_name`` to ``tools.human_preapproved`` in ``sevn.json``.

    Args:
        request (Request): FastAPI request with workspace state.
        tool_name (str): Tool registry name to pre-approve permanently.

    Returns:
        None: Persists via the unified config path when the name is new.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_persist_always_preapproved)
        True
    """

    on_disk = load_workspace_document(request)
    tools = dict(on_disk.get("tools") or {})
    existing_raw = tools.get("human_preapproved") or []
    existing = [str(x).strip() for x in existing_raw if str(x).strip()]
    if tool_name not in existing:
        existing.append(tool_name)
        tools["human_preapproved"] = existing
        on_disk["tools"] = tools
        persist_workspace_document(request, on_disk)


@router.get("/approvals/pending")
async def tool_approvals_pending(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> JSONResponse:
    """List pending tier-B tool approval decisions for the MC UI.

    Args:
        request (Request): Starlette request.
        _claims (DashboardClaims): Verified owner claims.

    Returns:
        JSONResponse: ``{"items": [...]}`` pending rows.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(tool_approvals_pending)
        True
    """

    bridge = _bridge(request)
    items = bridge.list_pending() if bridge is not None else []
    return JSONResponse(status_code=200, content={"items": items})


@router.post("/approvals/{decision_id}")
async def tool_approval_decide(
    decision_id: str,
    request: Request,
    body: ToolApprovalVerdictBody,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Submit an operator verdict for one pending tool approval.

    Args:
        decision_id (str): Pending decision uuid from ``mission.approval.pending``.
        request (Request): Starlette request.
        body (ToolApprovalVerdictBody): Verdict payload.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: ``200`` on success; ``404`` when decision is unknown or settled.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(tool_approval_decide)
        True
    """

    bridge = _bridge(request)
    if bridge is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": {"code": "bridge_unavailable", "message": "Approval bridge not wired"}
            },
        )

    pending = bridge.list_pending()
    row = next((item for item in pending if item["decision_id"] == decision_id), None)
    if row is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": "Unknown or settled decision_id"}},
        )

    verdict: ApprovalVerdict = body.verdict
    if verdict == "always":
        try:
            _persist_always_preapproved(request, str(row["tool_name"]))
        except (ValidationError, ValueError, OSError) as exc:
            return config_validation_error(exc)

    accepted = await bridge.submit_verdict(decision_id, verdict)
    if not accepted:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": "Unknown or settled decision_id"}},
        )

    await emit_mission_audit(
        request,
        kind="mission.approval.decided",
        hub_type="mission.approval.resolved",
        extra={
            "decision_id": decision_id,
            "tool_name": row["tool_name"],
            "session_id": row["session_id"],
            "turn_id": row["turn_id"],
            "verdict": verdict,
        },
    )

    return JSONResponse(
        status_code=200,
        content={"decision_id": decision_id, "verdict": verdict, "tool_name": row["tool_name"]},
    )


__all__ = [
    "ToolApprovalVerdictBody",
    "router",
    "tool_approval_decide",
    "tool_approvals_pending",
]
