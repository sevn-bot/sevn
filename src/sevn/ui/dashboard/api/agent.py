"""Mission Control Agent group REST router (`specs/24-dashboard.md` MC-7).

Module: sevn.ui.dashboard.api.agent
Depends: json, sqlite3, fastapi, sevn.code_understanding.graphify_mcp, sevn.config.model_resolution,
    sevn.onboarding, sevn.skills.manager, sevn.ui.dashboard.api.deps,
    sevn.ui.dashboard.services.tool_skill_health

Exports:
    tools_health_list — Tools & Skills Health panel data.
    skills_inventory — workspace skill registry with quarantine flags.
    skills_bundled_list — bundled skills installable under skills/user/.
    skills_install — copy bundled skill into skills/user/ (confirm-gated).
    skills_uninstall — remove skills/user/ skill (confirm-gated).
    skills_toggle — enable/disable user skill quarantine flag.
    skills_promote — graduate generated skill to user/.
    SkillInstallBody — install request schema.
    SkillToggleBody — enable/disable request schema.
    mcp_servers_registry — effective MCP descriptor registry.
    mcp_servers_put — persist workspace-scope ``mcp_enabled`` list.
    agent_permissions_get — editable ``permissions`` / ``tools`` subtrees.
    agent_permissions_put — persist ``permissions`` / ``tools`` to ``sevn.json``.
    agent_config_get — auxiliary model panel state.
    agent_config_put — persist ``providers.use_main_model_for_all`` and slot overrides.
    llm_params_get — workspace per-agent sampling-param document (or built-in default).
    llm_params_put — validate + atomically persist ``LLM_params_config.json``.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from sevn.code_understanding.graphify_mcp import build_effective_mcp_servers
from sevn.config.llm_params import (
    LLM_PARAMS_FILENAME,
    builtin_llm_params_doc,
    validate_llm_params_doc,
)
from sevn.config.model_resolution import (
    ModelSlot,
    list_catalog_model_ids,
    resolve_main_model_id,
    resolve_model_slot,
    use_main_model_for_all,
)
from sevn.config.workspace_config import WorkspaceConfig
from sevn.onboarding.draft_store import write_draft
from sevn.onboarding.promote import promote_draft
from sevn.onboarding.validate import validate_workspace_document
from sevn.skills import SkillExecutionError
from sevn.skills.manager import SkillsManager
from sevn.ui.dashboard.api._config_persist import (
    config_error,
    config_validation_error,
    load_workspace_document,
    persist_workspace_document,
    read_config_body,
)
from sevn.ui.dashboard.api.deps import require_dashboard_csrf, require_dashboard_owner
from sevn.ui.dashboard.services.auth import DashboardClaims
from sevn.ui.dashboard.services.mission_audit import emit_mission_audit
from sevn.ui.dashboard.services.ops_control import (
    confirm_token_valid,
    install_bundled_skill,
    list_bundled_skill_names,
    set_user_skill_quarantine,
    uninstall_user_skill,
)
from sevn.ui.dashboard.services.tool_skill_health import ToolSkillHealthService
from sevn.workspace.layout import WorkspaceLayout

router = APIRouter(prefix="/agent", tags=["dashboard-agent"])

_AGENT_CONFIG_SLOTS: tuple[tuple[str, ModelSlot], ...] = (
    ("triager", ModelSlot.triager),
    ("tier_b", ModelSlot.tier_b),
    ("tier_c", ModelSlot.tier_c),
    ("tier_d", ModelSlot.tier_d),
    ("c_sub_lm", ModelSlot.c_sub_lm),
    ("d_sub_lm", ModelSlot.d_sub_lm),
    ("c_lambda_leaf", ModelSlot.c_lambda_leaf),
    ("d_lambda_leaf", ModelSlot.d_lambda_leaf),
    ("lcm_summary", ModelSlot.lcm_summary),
    ("pre_compaction_flush", ModelSlot.pre_compaction_flush),
    ("dreaming_ranker", ModelSlot.dreaming_ranker),
    ("user_model_extractor", ModelSlot.user_model_extractor),
    ("scanner", ModelSlot.scanner),
)


def _workspace_id(workspace: WorkspaceConfig, layout: WorkspaceLayout) -> str:
    """Return the SQLite ``skills.workspace_id`` key for this deployment.

    Args:
        workspace (WorkspaceConfig): Parsed workspace.
        layout (WorkspaceLayout): Resolved layout.

    Returns:
        str: Workspace id string.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from pathlib import Path
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> cfg = WorkspaceConfig.minimal(workspace_root=".")
        >>> lay = WorkspaceLayout.from_config(Path("/tmp/w/sevn.json"), cfg)
        >>> _workspace_id(cfg, lay) == "."
        True
    """
    return workspace.workspace_root or str(layout.content_root)


def _error_response(code: str, message: str, *, status_code: int) -> JSONResponse:
    """Return a structured dashboard error envelope.

    Args:
        code (str): Stable error code.
        message (str): Human-readable message.
        status_code (int): HTTP status.

    Returns:
        JSONResponse: Error body.

    Examples:
        >>> _error_response("x", "y", status_code=400).status_code
        400
    """
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": {}}},
    )


async def _read_json_object(request: Request) -> dict[str, Any]:
    """Parse a JSON object body or return an empty dict.

    Args:
        request (Request): Incoming HTTP request.

    Returns:
        dict[str, Any]: Parsed object body.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_read_json_object)
        True
    """
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _suggest_auxiliary_models(main_model: str) -> dict[str, str]:
    """Return PRD §5.10 heuristic suggestions keyed by slot id.

    Args:
        main_model (str): Resolved triager / main catalog id.

    Returns:
        dict[str, str]: Suggested model ids per auxiliary slot key.

    Examples:
        >>> m = _suggest_auxiliary_models("anthropic/claude-sonnet-4-20250514")
        >>> "triager" in m
        True
    """
    mid = main_model.strip().lower()
    if "opus" in mid:
        triager = "anthropic/claude-haiku-4-20250514"
        aux = "anthropic/claude-sonnet-4-20250514"
    elif "sonnet" in mid or "claude" in mid:
        triager = "anthropic/claude-haiku-4-20250514"
        aux = triager
    elif "gpt-5" in mid or mid.startswith("openai/"):
        triager = "openai/gpt-5-mini"
        aux = triager
    elif mid.startswith("minimax/") or "gemma" in mid or "ollama" in mid:
        triager = main_model.strip()
        aux = main_model.strip()
    else:
        triager = main_model.strip()
        aux = main_model.strip()
    return {
        "triager": triager,
        "tier_b": aux,
        "tier_c": aux,
        "tier_d": aux,
        "c_sub_lm": aux,
        "d_sub_lm": aux,
        "c_lambda_leaf": aux,
        "d_lambda_leaf": aux,
        "lcm_summary": aux,
        "pre_compaction_flush": aux,
        "dreaming_ranker": aux,
        "user_model_extractor": aux,
        "scanner": aux,
    }


def _model_warnings(workspace: WorkspaceConfig) -> list[dict[str, str]]:
    """Return lightweight live warnings for the agent config panel.

    Args:
        workspace (WorkspaceConfig): Parsed workspace.

    Returns:
        list[dict[str, str]]: Warning rows with ``code`` and ``message``.

    Examples:
        >>> _model_warnings(WorkspaceConfig.minimal())
        []
    """
    warnings: list[dict[str, str]] = []
    if use_main_model_for_all(workspace):
        return warnings
    try:
        main = resolve_main_model_id(workspace)
        slots = {key: resolve_model_slot(workspace, slot) for key, slot in _AGENT_CONFIG_SLOTS}
    except Exception:
        return warnings
    regimes: set[str] = set()
    for model_id in slots.values():
        if "/" in model_id:
            regimes.add(model_id.split("/", 1)[0])
    if len(regimes) > 1:
        warnings.append(
            {
                "code": "mixed_budget_regimes",
                "message": "Multiple provider prefixes across slots — subscription metrics may be ambiguous.",
            },
        )
    if main != slots.get("triager"):
        warnings.append(
            {
                "code": "triager_slot_drift",
                "message": "Triager slot differs from resolved main model — review tier_default.triager.",
            },
        )
    return warnings


def _serialize_skill_inventory(manager: SkillsManager) -> list[dict[str, object]]:
    """Build skill list rows for the Skills tab.

    Args:
        manager (SkillsManager): Loaded skills registry.

    Returns:
        list[dict[str, object]]: Inventory rows.

    Examples:
        >>> _serialize_skill_inventory.__name__
        '_serialize_skill_inventory'
    """
    rows: list[dict[str, object]] = []
    for skill_id in sorted(manager.index.lines):
        record = manager.get_record(skill_id)
        rows.append(
            {
                "id": skill_id,
                "provenance": record.provenance,
                "version": record.manifest.version,
                "description": record.manifest.description,
                "quarantine": record.quarantine_runtime,
                "can_promote": record.provenance == "generated" and "/" not in skill_id,
                "script_count": len(record.manifest.scripts),
                "runnable_count": len(record.manifest.runnables),
                "path": str(record.skill_dir),
                "warnings": list(record.validation_errors),
            },
        )
    return rows


def _mcp_workspace_enabled(workspace: WorkspaceConfig) -> list[str]:
    """Read workspace-level ``mcp_enabled`` server id list from extras.

    Args:
        workspace (WorkspaceConfig): Parsed workspace.

    Returns:
        list[str]: Enabled server ids at workspace scope.

    Examples:
        >>> _mcp_workspace_enabled(WorkspaceConfig.minimal())
        []
    """
    raw = getattr(workspace, "mcp_enabled", None)
    if raw is None:
        extra = workspace.model_extra or {}
        raw = extra.get("mcp_enabled")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if isinstance(item, str) and item.strip()]


@router.get("/tools-health")
async def tools_health_list(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> JSONResponse:
    """List chronic tool/skill failure rows (`prd/07` §5.9).

    Args:
        request (Request): Starlette request (``sevn.db`` on app state).
        _claims (DashboardClaims): Verified owner claims.

    Returns:
        JSONResponse: Health rows and detector metadata.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(tools_health_list)
        True
    """
    workspace: WorkspaceConfig = request.app.state.workspace
    layout: WorkspaceLayout = request.app.state.layout
    conn: sqlite3.Connection = request.app.state.sqlite_conn
    svc = ToolSkillHealthService(workspace_id=_workspace_id(workspace, layout))
    rows = svc.list_rows(conn, source="dashboard")
    return JSONResponse(
        status_code=200,
        content={
            "rows": rows,
            "count": len(rows),
            "window_days": svc.window_days,
            "threshold": svc.threshold,
            "tools_table_wired": False,
        },
    )


@router.get("/skills")
async def skills_inventory(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> JSONResponse:
    """Return workspace skill inventory with quarantine flags.

    Args:
        request (Request): Starlette request.
        _claims (DashboardClaims): Verified owner claims.

    Returns:
        JSONResponse: Skill rows and registry version.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(skills_inventory)
        True
    """
    workspace: WorkspaceConfig = request.app.state.workspace
    layout: WorkspaceLayout = request.app.state.layout
    manager = SkillsManager.shared(
        layout.content_root,
        layout=layout,
        config=workspace,
    )
    return JSONResponse(
        status_code=200,
        content={
            "skills": _serialize_skill_inventory(manager),
            "registry_version": manager.registry_version,
            "count": len(manager.index.lines),
        },
    )


@router.post("/skills/{skill_name}/promote")
async def skills_promote(
    skill_name: str,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Promote ``generated/<name>/`` to ``user/<name>/`` (`specs/12` §2.5).

    Args:
        skill_name (str): Flat generated skill basename.
        request (Request): Starlette request.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified CSRF token.

    Returns:
        JSONResponse: Promotion result or structured error.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(skills_promote)
        True
    """
    workspace: WorkspaceConfig = request.app.state.workspace
    layout: WorkspaceLayout = request.app.state.layout
    manager = SkillsManager.shared(
        layout.content_root,
        layout=layout,
        config=workspace,
    )
    try:
        manager.promote_generated_to_user(skill_name)
    except SkillExecutionError as exc:
        return _error_response(exc.code.lower(), str(exc), status_code=422)
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "skill_name": skill_name,
            "registry_version": manager.registry_version,
        },
    )


class SkillInstallBody(BaseModel):
    """Install bundled skill into ``skills/user/``."""

    skill_name: str = Field(min_length=1)
    confirm_token: str | None = None


class SkillToggleBody(BaseModel):
    """Enable or disable a user skill via quarantine flag."""

    enabled: bool
    confirm_token: str | None = None


@router.get("/skills/bundled")
async def skills_bundled_list(
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> JSONResponse:
    """List bundled skills installable under ``skills/user/``.

    Args:
        _claims (DashboardClaims): Verified owner claims.

    Returns:
        JSONResponse: Sorted bundled skill names.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(skills_bundled_list)
        True
    """
    names = list_bundled_skill_names()
    return JSONResponse(status_code=200, content={"skills": names, "count": len(names)})


@router.post("/skills/install")
async def skills_install(
    body: SkillInstallBody,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Install a bundled skill copy into ``skills/user/`` (confirm-gated).

    Args:
        body (SkillInstallBody): Skill name and confirm token.
        request (Request): Starlette request.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified CSRF token.

    Returns:
        JSONResponse: Install result or structured error.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(skills_install)
        True
    """
    if not confirm_token_valid(body.model_dump()):
        return _error_response(
            "confirm_required",
            "skill install requires confirm_token",
            status_code=400,
        )
    workspace: WorkspaceConfig = request.app.state.workspace
    layout: WorkspaceLayout = request.app.state.layout
    try:
        result = install_bundled_skill(
            layout=layout,
            skill_name=body.skill_name,
            workspace=workspace,
        )
    except SkillExecutionError as exc:
        return _error_response(exc.code.lower(), str(exc), status_code=422)
    except ValueError as exc:
        return _error_response("skill_not_found", str(exc), status_code=404)
    await emit_mission_audit(
        request,
        kind="mission.ops.skill_install",
        op="skill_install",
        hub_type="mission.ops.changed",
        extra={"skill_name": body.skill_name},
    )
    return JSONResponse(status_code=201, content=result)


@router.delete("/skills/{skill_name}")
async def skills_uninstall(
    skill_name: str,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Remove a ``skills/user/`` skill (confirm-gated; never ``skills/core/``).

    Args:
        skill_name (str): Flat user skill basename.
        request (Request): Starlette request.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified CSRF token.

    Returns:
        JSONResponse: Uninstall result or structured error.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(skills_uninstall)
        True
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict) or not confirm_token_valid(body):
        return _error_response(
            "confirm_required",
            "skill uninstall requires confirm_token in JSON body",
            status_code=400,
        )
    workspace: WorkspaceConfig = request.app.state.workspace
    layout: WorkspaceLayout = request.app.state.layout
    try:
        result = uninstall_user_skill(
            layout=layout,
            skill_name=skill_name,
            workspace=workspace,
        )
    except SkillExecutionError as exc:
        code = 404 if exc.code == "SKILL_NOT_FOUND" else 422
        return _error_response(exc.code.lower(), str(exc), status_code=code)
    await emit_mission_audit(
        request,
        kind="mission.ops.skill_uninstall",
        op="skill_uninstall",
        hub_type="mission.ops.changed",
        extra={"skill_name": skill_name},
    )
    return JSONResponse(status_code=200, content=result)


@router.post("/skills/{skill_name}/toggle")
async def skills_toggle(
    skill_name: str,
    body: SkillToggleBody,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Enable or disable a user skill via quarantine frontmatter.

    Args:
        skill_name (str): Flat skill basename.
        body (SkillToggleBody): Enabled flag and confirm token.
        request (Request): Starlette request.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified CSRF token.

    Returns:
        JSONResponse: Toggle result or structured error.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(skills_toggle)
        True
    """
    if not confirm_token_valid(body.model_dump()):
        return _error_response(
            "confirm_required",
            "skill toggle requires confirm_token",
            status_code=400,
        )
    workspace: WorkspaceConfig = request.app.state.workspace
    layout: WorkspaceLayout = request.app.state.layout
    try:
        result = set_user_skill_quarantine(
            layout=layout,
            skill_name=skill_name,
            workspace=workspace,
            enabled=body.enabled,
        )
    except SkillExecutionError as exc:
        return _error_response(exc.code.lower(), str(exc), status_code=422)
    await emit_mission_audit(
        request,
        kind="mission.ops.skill_toggle",
        op="skill_toggle",
        hub_type="mission.ops.changed",
        extra={"skill_name": skill_name, "enabled": body.enabled},
    )
    return JSONResponse(status_code=200, content=result)


@router.get("/mcp-servers")
async def mcp_servers_registry(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> JSONResponse:
    """Return merged MCP stdio descriptor registry (read-only).

    Args:
        request (Request): Starlette request.
        _claims (DashboardClaims): Verified owner claims.

    Returns:
        JSONResponse: Server descriptors and workspace enablement.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(mcp_servers_registry)
        True
    """
    workspace: WorkspaceConfig = request.app.state.workspace
    layout: WorkspaceLayout = request.app.state.layout
    return JSONResponse(status_code=200, content=_mcp_servers_payload(workspace, layout))


def _mcp_servers_payload(workspace: WorkspaceConfig, layout: WorkspaceLayout) -> dict[str, object]:
    """Build the MCP Servers tab payload (effective registry + enablement).

    Args:
        workspace (WorkspaceConfig): Active workspace config.
        layout (WorkspaceLayout): Resolved workspace layout.

    Returns:
        dict[str, object]: Server descriptors, enabled ids, and count.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_mcp_servers_payload)
        True
    """

    effective = build_effective_mcp_servers(workspace, layout.content_root)
    enabled = _mcp_workspace_enabled(workspace)
    servers: list[dict[str, object]] = []
    for server_id, spec in sorted(effective.items()):
        if not isinstance(spec, dict):
            continue
        command = spec.get("command")
        args = spec.get("args")
        args_list = [str(a) for a in args] if isinstance(args, list) else []
        servers.append(
            {
                "server_id": server_id,
                "command": command if isinstance(command, str) else "",
                "args": args_list,
                "workspace_enabled": server_id in enabled,
                "synthetic": bool(spec.get("synthetic")),
            },
        )
    return {"servers": servers, "mcp_enabled": enabled, "count": len(servers)}


@router.put("/mcp-servers")
async def mcp_servers_put(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Persist the workspace-scope ``mcp_enabled`` list to ``sevn.json``.

    Args:
        request (Request): JSON body with ``mcp_enabled`` (list of server ids).
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: Updated MCP payload, ``400`` on bad body, ``422`` on unknown id.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(mcp_servers_put)
        True
    """

    body = await read_config_body(request)
    raw = body.get("mcp_enabled")
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        return config_error(
            "invalid_body",
            "body.mcp_enabled must be a list of server id strings",
            status_code=400,
        )
    workspace: WorkspaceConfig = request.app.state.workspace
    layout: WorkspaceLayout = request.app.state.layout
    known = set(build_effective_mcp_servers(workspace, layout.content_root))
    enabled: list[str] = []
    for server_id in raw:
        cleaned = server_id.strip()
        if not cleaned:
            continue
        if cleaned not in known:
            return config_error(
                "unknown_server",
                f"unknown MCP server id: {cleaned}",
                status_code=422,
            )
        if cleaned not in enabled:
            enabled.append(cleaned)
    on_disk = load_workspace_document(request)
    on_disk["mcp_enabled"] = enabled
    try:
        ws = persist_workspace_document(request, on_disk)
    except (ValidationError, ValueError, OSError) as exc:
        return config_validation_error(exc)
    return JSONResponse(status_code=200, content=_mcp_servers_payload(ws, layout))


def _permissions_payload(workspace: WorkspaceConfig) -> dict[str, object]:
    """Project the editable ``permissions`` and ``tools`` config subtrees.

    Args:
        workspace (WorkspaceConfig): Active workspace config.

    Returns:
        dict[str, object]: Current permissions and tools mappings.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_permissions_payload)
        True
    """

    return {
        "permissions": dict(workspace.permissions or {}),
        "tools": dict(workspace.tools or {}),
    }


@router.get("/permissions")
async def agent_permissions_get(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> JSONResponse:
    """Return the editable ``permissions`` / ``tools`` config for the tab.

    Args:
        request (Request): Starlette request.
        _claims (DashboardClaims): Verified owner claims.

    Returns:
        JSONResponse: Current permissions and tools mappings.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(agent_permissions_get)
        True
    """

    workspace: WorkspaceConfig = request.app.state.workspace
    return JSONResponse(status_code=200, content=_permissions_payload(workspace))


@router.put("/permissions")
async def agent_permissions_put(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Persist ``permissions`` and/or ``tools`` subtrees to ``sevn.json``.

    Args:
        request (Request): JSON body with optional ``permissions`` / ``tools`` objects.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: Updated payload, ``400`` on bad body, ``422`` on schema failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(agent_permissions_put)
        True
    """

    body = await read_config_body(request)
    perms = body.get("permissions")
    tools = body.get("tools")
    if perms is not None and not isinstance(perms, dict):
        return config_error(
            "invalid_body", "body.permissions must be a JSON object", status_code=400
        )
    if tools is not None and not isinstance(tools, dict):
        return config_error("invalid_body", "body.tools must be a JSON object", status_code=400)
    if perms is None and tools is None:
        return config_error(
            "invalid_body",
            "body must include permissions and/or tools",
            status_code=400,
        )
    on_disk = load_workspace_document(request)
    if perms is not None:
        on_disk["permissions"] = perms
    if tools is not None:
        on_disk["tools"] = tools
    try:
        ws = persist_workspace_document(request, on_disk)
    except (ValidationError, ValueError, OSError) as exc:
        return config_validation_error(exc)
    return JSONResponse(status_code=200, content=_permissions_payload(ws))


@router.get("/config")
async def agent_config_get(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> JSONResponse:
    """Return auxiliary model panel state (`prd/07` §5.10).

    Args:
        request (Request): Starlette request.
        _claims (DashboardClaims): Verified owner claims.

    Returns:
        JSONResponse: Unified flag, resolved slots, suggestions, warnings.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(agent_config_get)
        True
    """
    workspace: WorkspaceConfig = request.app.state.workspace
    unified = use_main_model_for_all(workspace)
    try:
        main_model = resolve_main_model_id(workspace)
    except Exception as exc:
        return _error_response("triager_unavailable", str(exc), status_code=422)
    slots: list[dict[str, object]] = []
    for key, slot in _AGENT_CONFIG_SLOTS:
        try:
            resolved = resolve_model_slot(workspace, slot)
        except Exception:
            resolved = main_model
        slots.append(
            {"slot": key, "resolved": resolved, "editable": not unified or key == "triager"}
        )
    suggestions = _suggest_auxiliary_models(main_model)
    return JSONResponse(
        status_code=200,
        content={
            "use_main_model_for_all": unified,
            "main_model": main_model,
            "slots": slots,
            "catalog_model_ids": list_catalog_model_ids(workspace),
            "suggestions": suggestions,
            "warnings": _model_warnings(workspace),
        },
    )


@router.put("/config")
async def agent_config_put(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Persist agent model panel fields into ``sevn.json``.

    Args:
        request (Request): JSON body with ``use_main_model_for_all`` and optional ``providers``.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified CSRF token.

    Returns:
        JSONResponse: ``200`` on success or ``422`` on validation failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(agent_config_put)
        True
    """
    body = await _read_json_object(request)
    layout: WorkspaceLayout = request.app.state.layout
    sevn_json = layout.sevn_json_path
    try:
        doc = json.loads(sevn_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _error_response("config_read_failed", str(exc), status_code=422)
    if not isinstance(doc, dict):
        return _error_response("config_read_failed", "sevn.json must be an object", status_code=422)
    providers_patch = body.get("providers")
    if isinstance(providers_patch, dict):
        doc.setdefault("providers", {})
        if isinstance(doc["providers"], dict):
            for key, val in providers_patch.items():
                doc["providers"][key] = val
    if "use_main_model_for_all" in body:
        doc.setdefault("providers", {})
        if isinstance(doc["providers"], dict):
            doc["providers"]["use_main_model_for_all"] = bool(body["use_main_model_for_all"])
    try:
        from sevn.onboarding.web_app import apply_model_slot_policy

        apply_model_slot_policy(doc)
        validate_workspace_document(doc, check_provider_credentials=False)
        write_draft(sevn_json, doc)
        promote_draft(
            sevn_json, backup_previous=sevn_json.is_file(), check_provider_credentials=False
        )
    except (ValidationError, ValueError, OSError) as exc:
        return _error_response("validation_failed", str(exc), status_code=422)
    return JSONResponse(status_code=200, content={"ok": True, "sevn_json": str(sevn_json)})


@router.get("/llm-params")
async def llm_params_get(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> JSONResponse:
    """Return the workspace per-agent sampling-param document (`W7`/`W8`, D3).

    Reads ``<content_root>/LLM_params_config.json`` when present and valid;
    otherwise returns the built-in default document. Sampling params here win
    over ``sevn.json`` (model selection only); a documented gateway restart is
    required for edits to take effect (agents read the file at runtime).

    Args:
        request (Request): Starlette request (``layout`` on app state).
        _claims (DashboardClaims): Verified owner claims.

    Returns:
        JSONResponse: ``{"doc": <params>, "source": "workspace"|"builtin", ...}``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(llm_params_get)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    path = layout.content_root / LLM_PARAMS_FILENAME
    source = "builtin"
    doc: dict[str, Any] = builtin_llm_params_doc()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        raw = None
    if raw is not None:
        try:
            parsed = json.loads(raw)
            doc = validate_llm_params_doc(parsed)
            source = "workspace"
        except (ValueError, json.JSONDecodeError):
            source = "builtin"
    return JSONResponse(
        status_code=200,
        content={
            "doc": doc,
            "source": source,
            "path": str(path),
            "restart_required": True,
        },
    )


@router.put("/llm-params")
async def llm_params_put(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Validate and persist the workspace ``LLM_params_config.json`` (`W8`, D3).

    The request body is validated via :func:`validate_llm_params_doc` and then
    atomically written to ``<content_root>/LLM_params_config.json``. This does
    **not** route through ``sevn.json`` — sampling params live in their own
    workspace file. A gateway restart applies the change.

    Args:
        request (Request): JSON body holding the params document (optionally
            wrapped as ``{"doc": {...}}``).
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified CSRF token.

    Returns:
        JSONResponse: ``200`` on success or ``422`` on validation/write failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(llm_params_put)
        True
    """
    body = await _read_json_object(request)
    candidate = body.get("doc") if isinstance(body.get("doc"), dict) else body
    try:
        doc = validate_llm_params_doc(candidate)
    except ValueError as exc:
        return _error_response("validation_failed", str(exc), status_code=422)
    layout: WorkspaceLayout = request.app.state.layout
    path = layout.content_root / LLM_PARAMS_FILENAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        return _error_response("params_write_failed", str(exc), status_code=422)
    return JSONResponse(
        status_code=200,
        content={"ok": True, "path": str(path), "restart_required": True},
    )


__all__ = [
    "agent_config_get",
    "agent_config_put",
    "agent_permissions_get",
    "agent_permissions_put",
    "llm_params_get",
    "llm_params_put",
    "mcp_servers_put",
    "mcp_servers_registry",
    "router",
    "skills_bundled_list",
    "skills_install",
    "skills_inventory",
    "skills_promote",
    "skills_toggle",
    "skills_uninstall",
    "tools_health_list",
]
