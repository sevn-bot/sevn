"""Mission Control Coding Agents hub REST router (CA1 + CA6.2 artifacts).

Module: sevn.ui.dashboard.api.coding_agents
Depends: fastapi, sevn.coding_agents, sevn.coding_agents.artifacts,
    sevn.config.sections.coding_agents, sevn.ui.dashboard.api.deps

Exports:
    coding_agents_list — list configured agents, bindings, and run status.
    coding_agents_put — persist ``coding_agents`` subtree in ``sevn.json``.
    coding_agents_list_payload — pure list payload helper for tests.
    coding_agents_artifacts_list — list all artifact runs from vault.
    coding_agents_run_artifacts — list artifacts for one run.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from sevn.coding_agents.artifacts import list_all_runs, list_run_artifacts
from sevn.coding_agents.migrate import migrate_legacy_claude_agent_topic
from sevn.coding_agents.registry import list_agent_summaries
from sevn.config.sections.coding_agents import parse_coding_agents_section
from sevn.config.workspace_config import WorkspaceConfig
from sevn.ui.dashboard.api._config_persist import (
    config_error,
    config_validation_error,
    deep_merge,
    load_workspace_document,
    persist_workspace_document,
    read_config_body,
)
from sevn.ui.dashboard.api.deps import require_dashboard_csrf, require_dashboard_owner
from sevn.ui.dashboard.services.auth import DashboardClaims

router = APIRouter(prefix="/coding-agents", tags=["dashboard-coding-agents"])


def _section_enabled(workspace: WorkspaceConfig) -> bool:
    """Return whether the hub master toggle is enabled.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.

    Returns:
        bool: ``coding_agents.enabled`` when section exists, else ``False``.

    Examples:
        >>> _section_enabled(WorkspaceConfig.minimal())
        False
    """
    extra = workspace.model_extra or {}
    section = parse_coding_agents_section(extra.get("coding_agents"))
    if section is None:
        return False
    return bool(section.enabled)


def coding_agents_list_payload(workspace: WorkspaceConfig) -> dict[str, Any]:
    """Build list payload for unit tests and internal callers.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.

    Returns:
        dict[str, Any]: Same shape as ``GET /api/v1/coding-agents``.

    Examples:
        >>> coding_agents_list_payload(WorkspaceConfig.minimal())["count"]
        0
    """
    agents = list_agent_summaries(workspace)
    return {
        "enabled": _section_enabled(workspace),
        "agents": agents,
        "count": len(agents),
    }


@router.get("")
async def coding_agents_list(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, Any]:
    """List coding agents for the Mission Control hub tab.

    Args:
        request (Request): FastAPI request with workspace on ``app.state``.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, Any]: Agents, bindings summary, and idle run status placeholders.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(coding_agents_list)
        True
    """
    workspace: WorkspaceConfig = request.app.state.workspace
    return coding_agents_list_payload(workspace)


@router.put("")
async def coding_agents_put(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Patch the ``coding_agents`` subtree in ``sevn.json``.

    Args:
        request (Request): HTTP request carrying JSON patch body.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): CSRF gate (side effect only).

    Returns:
        JSONResponse: Updated agent list envelope or structured error.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(coding_agents_put)
        True
    """
    body = await read_config_body(request)
    if not isinstance(body, dict):
        return config_error("invalid_body", "JSON object required", status_code=400)
    patch = body.get("coding_agents", body)
    if not isinstance(patch, dict):
        return config_error("invalid_body", "coding_agents object required", status_code=400)
    try:
        doc = load_workspace_document(request)
        migrated, _changed = migrate_legacy_claude_agent_topic(doc)
        merged = deep_merge(migrated, {"coding_agents": patch})
        parse_coding_agents_section(merged.get("coding_agents"))
        workspace = persist_workspace_document(request, merged)
    except ValidationError as exc:
        return config_validation_error(exc)
    except ValueError as exc:
        return config_error("validation_failed", str(exc), status_code=422)
    except OSError as exc:
        return config_error("persist_failed", str(exc), status_code=500)

    return JSONResponse(coding_agents_list_payload(workspace))


@router.get("/artifacts")
async def coding_agents_artifacts_list(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, Any]:
    """List all artifact runs from the ALRCA vault.

    Args:
        request (Request): FastAPI request with workspace on ``app.state``.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, Any]: ``{"runs": [...], "count": int}`` envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(coding_agents_artifacts_list)
        True
    """
    workspace_path = getattr(request.app.state, "workspace_path", None)
    if workspace_path is None:
        workspace: WorkspaceConfig = request.app.state.workspace
        workspace_path = getattr(workspace, "workspace_path", None)
    if workspace_path is None:
        return {"runs": [], "count": 0}
    from pathlib import Path

    runs = list_all_runs(Path(str(workspace_path)))
    return {"runs": runs, "count": len(runs)}


@router.get("/artifacts/{run_id}")
async def coding_agents_run_artifacts(
    run_id: str,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, Any]:
    """List artifacts for one ALRCA run.

    Args:
        run_id (str): ALRCA run identifier.
        request (Request): FastAPI request.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, Any]: ``{"run_id": ..., "artifacts": [...], "count": int}`` envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(coding_agents_run_artifacts)
        True
    """
    workspace_path = getattr(request.app.state, "workspace_path", None)
    if workspace_path is None:
        workspace: WorkspaceConfig = request.app.state.workspace
        workspace_path = getattr(workspace, "workspace_path", None)
    if workspace_path is None:
        return {"run_id": run_id, "artifacts": [], "count": 0}
    from pathlib import Path

    artifacts = list_run_artifacts(run_id, Path(str(workspace_path)))
    return {"run_id": run_id, "artifacts": artifacts, "count": len(artifacts)}


__all__ = [
    "coding_agents_artifacts_list",
    "coding_agents_list",
    "coding_agents_list_payload",
    "coding_agents_put",
    "coding_agents_run_artifacts",
    "router",
]
