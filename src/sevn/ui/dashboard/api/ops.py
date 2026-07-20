"""Mission Control Ops group REST router (`specs/24-dashboard.md` MC-6).

Module: sevn.ui.dashboard.api.ops
Depends: json, re, sqlite3, fastapi, sevn.cli.workspace_schema, sevn.onboarding,
    sevn.security.sandbox_runtime, sevn.triggers.cron, sevn.ui.dashboard.api.deps,
    sevn.ui.dashboard.services.auth, sevn.infrastructure.tunnel_manager

Exports:
    config_full_get — unified schema-driven Config tab bootstrap payload.
    config_full_put — validate/persist full ``sevn.json`` with redaction merge.
    config_full_validate — dry-run validation for the unified Config tab.
    config_get — read redacted ``sevn.json`` for the Config tab.
    cron_jobs_list — workspace cron rows from ``sevn.db``.
    cron_config_put — persist the ``triggers.paused`` scheduler flag.
    security_get — ``security.*`` subtree + scanner posture.
    security_put — patch ``security.*`` toggles in ``sevn.json``.
    tracing_logfire_get — Logfire export status for Mission Control.
    tracing_logfire_put — enable/disable Logfire export and store tokens.
    mission_subagents_get — live sub-agent counts, running rows, recent history.
    mission_subagent_kill — kill one tracked sub-agent run (owner+CSRF).
    mission_subagents_kill_all — kill all active level-1 runs (owner+CSRF).
    secrets_aliases — read-only redacted secret alias inventory.
    secrets_alias_reveal — owner+CSRF audited resolve for ``${SECRET:…}`` aliases.
    tunnels_status — tunnel mode, gateway bind, doctor-style probes + process health.
    tunnels_process — live tunnel process health (pid, healthy, public_url).
    tunnels_start — start configured tunnel provider (confirm gate, owner+CSRF).
    tunnels_stop — stop configured tunnel provider (confirm gate, owner+CSRF).
    backup_manifest — config backups + sandbox snapshot inventory.
    schema_ontology — JSON schema metadata + ontology index (read-only).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from sevn.agent.tracing.logfire_config import (
    DEFAULT_LOGFIRE_TOKEN_REF,
    LOGFIRE_SECRET_LOGICAL_KEY,
    apply_logfire_export_to_sevn_doc,
    logfire_export_status,
)
from sevn.cli.repo_sync import RepoSyncError, resolve_sevn_repo_root
from sevn.cli.workspace_schema import load_workspace_json_schema
from sevn.config.loader import load_workspace
from sevn.config.version_id import resolve_version_id
from sevn.config.workspace_config import (
    SecurityWorkspaceConfig,
    TriggersWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.mission.mission_api import (
    fetch_subagents_mission_payload,
    kill_all_subagents_mission,
    kill_subagent_mission,
)
from sevn.infrastructure.tunnel_config import prepare_tunnel_runtime_cfg, tunnel_cfg_from_workspace
from sevn.infrastructure.tunnel_manager import TunnelStatus, default_manager
from sevn.onboarding.draft_store import write_draft
from sevn.onboarding.live_validate import (
    ValidationCheck,
    probe_llm_reachability,
    probe_secrets_backend,
)
from sevn.onboarding.promote import promote_draft
from sevn.onboarding.validate import validate_workspace_document
from sevn.security.sandbox_runtime import snapshots_dir
from sevn.security.secrets.errors import SecretsStoreCorruptError, is_encrypted_store_unlock_error
from sevn.security.secrets.factory import secrets_chain_from_workspace
from sevn.triggers.cron import cron_job_to_dict, list_cron_jobs
from sevn.ui.dashboard.api._config_persist import (
    load_workspace_document,
    persist_workspace_document,
    read_config_body,
)
from sevn.ui.dashboard.api.deps import require_dashboard_csrf, require_dashboard_owner
from sevn.ui.dashboard.api.secrets_store import SecretRevealResponse
from sevn.ui.dashboard.services.auth import (
    DashboardClaims,
)
from sevn.ui.dashboard.services.config_full import (
    changed_top_level_keys,
    merge_redacted_config,
    validate_against_json_schema,
    validate_config_document,
    validation_errors_from_exception,
)
from sevn.ui.dashboard.services.mission_audit import emit_mission_audit
from sevn.workspace.layout import WorkspaceLayout

router = APIRouter(tags=["dashboard-ops"])

_SECRET_REF_PATTERN = re.compile(r"\$\{SECRET:([^}]+)\}")
_SENSITIVE_KEY_RE = re.compile(r"(token|secret|password|api[_-]?key|credential|jwt)", re.IGNORECASE)


def _error_response(
    code: str,
    message: str,
    *,
    status_code: int,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    """Return a structured dashboard error envelope.

    Args:
        code (str): Stable error code.
        message (str): Human-readable message.
        status_code (int): HTTP status.
        details (dict[str, object] | None): Optional machine details.

    Returns:
        JSONResponse: Error body.

    Examples:
        >>> _error_response("x", "y", status_code=400).status_code
        400
    """

    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
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


def _field_errors_response(errors: list[dict[str, str]]) -> JSONResponse:
    """Return structured field errors for unified config validation.

    Args:
        errors (list[dict[str, str]]): Rows with ``path`` and ``message``.

    Returns:
        JSONResponse: HTTP 422 with an ``errors`` array.

    Examples:
        >>> _field_errors_response([{"path": "gateway.port", "message": "bad"}]).status_code
        422
    """

    detail = (
        "; ".join(f"{row['path']}: {row['message']}" for row in errors[:8]) or "validation failed"
    )
    return JSONResponse(
        status_code=422,
        content={
            "errors": errors,
            "error": {
                "code": "validation_failed",
                "message": detail,
                "details": {"errors": errors},
            },
        },
    )


def _validation_error_response(exc: Exception) -> JSONResponse:
    """Map validation failures to dashboard **422**.

    Args:
        exc (Exception): Validation or schema failure.

    Returns:
        JSONResponse: Structured validation error.

    Examples:
        >>> _validation_error_response(ValueError("bad")).status_code
        422
    """

    if isinstance(exc, ValidationError):
        detail = "; ".join(err["msg"] for err in exc.errors()[:8]) or "validation failed"
    else:
        detail = str(exc)
    return _error_response("validation_failed", detail, status_code=422)


def _collect_secret_ref_logical_keys(node: object, *, keys: set[str]) -> None:
    """Walk a JSON tree and collect ``${SECRET:…}`` logical keys.

    Args:
        node (object): JSON subtree.
        keys (set[str]): Accumulator (mutated in place).

    Returns:
        None: Mutates *keys* only.

    Examples:
        >>> acc: set[str] = set()
        >>> _collect_secret_ref_logical_keys("${SECRET:k:alpha}", keys=acc)
        >>> "alpha" in acc
        True
    """

    if isinstance(node, str):
        for match in _SECRET_REF_PATTERN.finditer(node):
            inner = match.group(1)
            if ":" in inner:
                _, logical = inner.split(":", 1)
                logical_key = logical.strip()
                if logical_key:
                    keys.add(logical_key)
        return
    if isinstance(node, dict):
        for value in node.values():
            _collect_secret_ref_logical_keys(value, keys=keys)
        return
    if isinstance(node, list):
        for item in node:
            _collect_secret_ref_logical_keys(item, keys=keys)


def _redact_secret_refs_in_value(value: object) -> object:
    """Replace ``${SECRET:…}`` strings with redacted placeholders.

    Args:
        value (object): JSON scalar or container.

    Returns:
        object: Redacted copy.

    Examples:
        >>> _redact_secret_refs_in_value("${SECRET:k:tok}")
        '<redacted-secret-ref>'
    """

    if isinstance(value, str):
        if _SECRET_REF_PATTERN.search(value):
            return "<redacted-secret-ref>"
        return value
    if isinstance(value, dict):
        return {k: _redact_secret_refs_in_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_secret_refs_in_value(item) for item in value]
    return value


def _config_version_id(
    layout: WorkspaceLayout,
    raw: dict[str, Any],
    *,
    request: Request | None = None,
) -> str:
    """Return the effective build ``version_id`` for Mission Control (D4).

    Prefers the persisted ``sevn.json`` value, then a gateway router stash when
    the dashboard shares a live gateway process, else :func:`resolve_version_id`.

    Args:
        layout (WorkspaceLayout): Active workspace layout.
        raw (dict[str, Any]): Parsed ``sevn.json`` document (unredacted).
        request (Request | None, optional): FastAPI request for router stash lookup.

    Returns:
        str: Non-empty build identity string for operators.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> lay = WorkspaceLayout(Path("/tmp/sevn.json"), Path("/tmp"))
        >>> _config_version_id(lay, {"version_id": " build-1 "})
        'build-1'
    """
    existing = raw.get("version_id")
    if isinstance(existing, str) and existing.strip():
        return existing.strip()
    if request is not None:
        router = getattr(request.app.state, "gateway_router", None)
        if router is not None:
            stashed = getattr(router, "_version_id", None)
            if isinstance(stashed, str) and stashed.strip():
                return stashed.strip()
    return resolve_version_id(repo_root=layout.content_root)


def _redact_config_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Redact secret refs and sensitive keys for dashboard display.

    Args:
        doc (dict[str, Any]): Raw workspace document.

    Returns:
        dict[str, Any]: Redacted shallow copy safe for Mission Control.

    Examples:
        >>> out = _redact_config_document({"api_key": "x", "gateway": {"port": 1}})
        >>> out["api_key"]
        '<redacted>'
    """

    def _walk(node: object, parent_key: str | None) -> object:
        if isinstance(node, dict):
            out: dict[str, Any] = {}
            for key, val in node.items():
                if _SENSITIVE_KEY_RE.search(key):
                    out[key] = "<redacted>"
                else:
                    out[key] = _walk(val, key)
            return out
        if isinstance(node, list):
            return [_walk(item, parent_key) for item in node]
        if isinstance(node, str):
            if _SECRET_REF_PATTERN.search(node):
                return "<redacted-secret-ref>"
            if parent_key and _SENSITIVE_KEY_RE.search(parent_key):
                return "<redacted>"
        return node

    redacted = _walk(doc, None)
    return redacted if isinstance(redacted, dict) else doc


def _list_config_backups(sevn_json: Path) -> list[dict[str, object]]:
    """List ``sevn.json.v*`` backup files beside the active config.

    Args:
        sevn_json (Path): Active ``sevn.json`` path.

    Returns:
        list[dict[str, object]]: Backup file metadata (no contents).

    Examples:
        >>> _list_config_backups(Path("/tmp/none/sevn.json"))
        []
    """

    parent = sevn_json.parent
    if not parent.is_dir():
        return []
    entries: list[dict[str, object]] = []
    for path in sorted(parent.glob("sevn.json.v*")):
        if not path.is_file():
            continue
        stat = path.stat()
        entries.append(
            {
                "name": path.name,
                "path": str(path),
                "size_bytes": stat.st_size,
                "modified_unix_s": int(stat.st_mtime),
            },
        )
    return entries


def _list_snapshot_tarballs(layout: WorkspaceLayout) -> list[dict[str, object]]:
    """List sandbox snapshot tarballs under ``.sevn/sandbox-snapshots``.

    Args:
        layout (WorkspaceLayout): Resolved workspace paths.

    Returns:
        list[dict[str, object]]: Tarball metadata (newest first).

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> lay = WorkspaceLayout.from_config(
        ...     Path("/tmp/w/sevn.json"),
        ...     WorkspaceConfig.minimal(),
        ... )
        >>> _list_snapshot_tarballs(lay) == [] or isinstance(_list_snapshot_tarballs(lay), list)
        True
    """

    root = snapshots_dir(layout)
    if not root.is_dir():
        return []
    rows: list[dict[str, object]] = []
    for path in sorted(root.glob("*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_file():
            continue
        stat = path.stat()
        rows.append(
            {
                "name": path.name,
                "path": str(path),
                "size_bytes": stat.st_size,
                "modified_unix_s": int(stat.st_mtime),
            },
        )
    return rows


def _parse_specs_index_markdown(text: str) -> list[dict[str, str]]:
    """Parse ``evolution/specs-index.md`` table rows into entries.

    Args:
        text (str): Markdown file contents.

    Returns:
        list[dict[str, str]]: Spec id, file, scope, and parent PRD when present.

    Examples:
        >>> rows = _parse_specs_index_markdown("| 10 | [`10-x.md`](x) | scope | PRD |\\n")
        >>> rows[0]["id"]
        '10'
    """

    entries: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith(("| #", "|---")):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 3 or not cells[0].isdigit():
            continue
        file_cell = cells[1]
        match = re.search(r"\[`([^`]+)`\]", file_cell)
        file_name = match.group(1) if match else file_cell
        entries.append(
            {
                "id": cells[0],
                "file": file_name,
                "scope": cells[2],
                "parent_prd": cells[3] if len(cells) > 3 else "",
            },
        )
    return entries


def _ontology_index_payload() -> dict[str, object]:
    """Load read-only ontology/spec index from the checkout when available.

    Returns:
        dict[str, object]: Index path, entries, and load status.

    Examples:
        >>> body = _ontology_index_payload()
        >>> "entries" in body
        True
    """

    try:
        repo = resolve_sevn_repo_root()
    except (OSError, ValueError, RepoSyncError):
        return {"available": False, "path": "", "entries": [], "reason": "repo_root_unresolved"}
    index_path = repo / "evolution" / "specs-index.md"
    if not index_path.is_file():
        return {
            "available": False,
            "path": str(index_path),
            "entries": [],
            "reason": "specs_index_missing",
        }
    text = index_path.read_text(encoding="utf-8")
    return {
        "available": True,
        "path": str(index_path),
        "entries": _parse_specs_index_markdown(text),
    }


def _security_payload(workspace: WorkspaceConfig) -> dict[str, object]:
    """Project ``security.*`` for the Security tab.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.

    Returns:
        dict[str, object]: Security subtree and scanner summary.

    Examples:
        >>> body = _security_payload(WorkspaceConfig.minimal())
        >>> "security" in body
        True
    """

    sec = workspace.security
    dumped = sec.model_dump(mode="python", exclude_none=True) if sec is not None else {}
    scanner = sec.scanner if sec is not None else None
    return {
        "security": dumped,
        "scanner_summary": {
            "heuristic_only": bool(scanner.heuristic_only) if scanner else False,
            "bypass_owner": bool(scanner.bypass_owner) if scanner else False,
            "image_ocr": bool(scanner.image_ocr) if scanner else False,
            "scan_voice": bool(scanner.scan_voice) if scanner else True,
        },
    }


def _validation_check_row(check: ValidationCheck) -> dict[str, object]:
    """Map a live-validation probe to a tunnels doctor row.

    Args:
        check (ValidationCheck): Probe outcome.

    Returns:
        dict[str, object]: JSON-serializable probe row.

    Examples:
        >>> from sevn.onboarding.live_validate import ValidationCheck
        >>> _validation_check_row(ValidationCheck("x", True, "info", "ok"))["check_id"]
        'x'
    """

    return {
        "check_id": check.check_id,
        "ok": check.ok,
        "severity": check.severity,
        "detail": check.detail,
        "hint": check.hint,
    }


async def _config_full_payload(request: Request) -> dict[str, object]:
    """Build the unified Config tab GET payload.

    Args:
        request (Request): FastAPI request with layout and workspace on ``app.state``.

    Returns:
        dict[str, object]: Redacted config, schema, and metadata.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_config_full_payload)
        True
    """

    layout: WorkspaceLayout = request.app.state.layout
    ws: WorkspaceConfig = request.app.state.workspace
    raw = load_workspace_document(request)
    try:
        schema_doc = load_workspace_json_schema()
    except (OSError, json.JSONDecodeError, FileNotFoundError, ValueError) as exc:
        schema_doc = {"error": str(exc)}
    return {
        "config": _redact_config_document(raw),
        "schema": schema_doc,
        "schema_version": ws.schema_version,
        "sevn_json_path": str(layout.sevn_json_path),
    }


async def _apply_config_full_body(
    request: Request,
    body: dict[str, Any],
    *,
    dry_run: bool,
) -> JSONResponse:
    """Validate and optionally persist a unified config document.

    Args:
        request (Request): FastAPI request.
        body (dict[str, Any]): Candidate full ``sevn.json`` from the editor.
        dry_run (bool): When ``True``, validate only and write nothing.

    Returns:
        JSONResponse: Success payload or structured ``422`` field errors.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_apply_config_full_body)
        True
    """

    if not body:
        return _error_response(
            "invalid_body",
            "body must be a non-empty JSON object",
            status_code=400,
        )
    on_disk = load_workspace_document(request)
    merged = merge_redacted_config(body, on_disk)
    schema_errors = validate_against_json_schema(merged)
    if schema_errors:
        return _field_errors_response(schema_errors)
    try:
        validate_config_document(merged)
    except Exception as exc:
        return _field_errors_response(validation_errors_from_exception(exc))
    if dry_run:
        payload = await _config_full_payload(request)
        payload["ok"] = True
        payload["dry_run"] = True
        payload["config"] = _redact_config_document(merged)
        return JSONResponse(status_code=200, content=payload)
    changed_keys = changed_top_level_keys(on_disk, merged)
    persist_workspace_document(request, merged)
    await emit_mission_audit(
        request,
        kind="mission.config.write",
        hub_type="mission.config.changed",
        extra={"keys": changed_keys},
    )
    payload = await _config_full_payload(request)
    payload["ok"] = True
    payload["dry_run"] = False
    payload["changed_keys"] = changed_keys
    return JSONResponse(status_code=200, content=payload)


@router.get("/config/full")
async def config_full_get(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return redacted ``sevn.json``, bundled schema, and metadata for the Config tab.

    Args:
        request (Request): FastAPI request with layout on ``app.state``.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Unified config editor bootstrap payload.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(config_full_get)
        True
    """

    return await _config_full_payload(request)


@router.put("/config/full")
async def config_full_put(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Validate and persist a full ``sevn.json`` with redaction-preserving merge.

    Query ``?dry_run=1`` validates without writing.

    Args:
        request (Request): JSON body is the candidate workspace document.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: Redacted echo on success or ``422`` field errors.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(config_full_put)
        True
    """

    body = await read_config_body(request)
    dry_run = request.query_params.get("dry_run", "").strip().lower() in {"1", "true", "yes"}
    return await _apply_config_full_body(request, body, dry_run=dry_run)


@router.post("/config/full/validate")
async def config_full_validate(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Validate a candidate full ``sevn.json`` without persisting (alias of dry-run PUT).

    Args:
        request (Request): JSON body is the candidate workspace document.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: ``200`` when valid or ``422`` with field errors.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(config_full_validate)
        True
    """

    body = await read_config_body(request)
    return await _apply_config_full_body(request, body, dry_run=True)


@router.get("/config")
async def config_get(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return the active workspace document with secrets redacted.

    Args:
        request (Request): FastAPI request with layout on ``app.state``.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Redacted config, path, and schema version.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(config_get)
        True
    """

    layout: WorkspaceLayout = request.app.state.layout
    ws: WorkspaceConfig = request.app.state.workspace
    raw = json.loads(layout.sevn_json_path.read_text(encoding="utf-8"))
    return {
        "sevn_json": str(layout.sevn_json_path),
        "schema_version": ws.schema_version,
        "version_id": _config_version_id(layout, raw, request=request),
        "document": _redact_config_document(raw),
    }


@router.get("/cron/jobs")
async def cron_jobs_list(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """List persisted cron jobs from workspace ``sevn.db``.

    Args:
        request (Request): FastAPI request with sqlite connection.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Cron job rows (no secret payloads).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(cron_jobs_list)
        True
    """

    conn = request.app.state.sqlite_conn
    ws: WorkspaceConfig = request.app.state.workspace
    return _cron_payload(conn, ws)


def _cron_payload(conn: Any, ws: WorkspaceConfig) -> dict[str, object]:
    """Build the Cron tab payload (persisted jobs + paused flag).

    Args:
        conn (Any): Workspace ``sevn.db`` connection.
        ws (WorkspaceConfig): Active workspace config.

    Returns:
        dict[str, object]: Cron job rows, count, and ``triggers.paused`` flag.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_cron_payload)
        True
    """

    jobs = [cron_job_to_dict(job) for job in list_cron_jobs(conn)]
    paused = bool(ws.triggers and ws.triggers.paused)
    return {"jobs": jobs, "count": len(jobs), "triggers_paused": paused}


@router.put("/cron/config")
async def cron_config_put(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Persist the ``triggers.paused`` scheduler flag to ``sevn.json``.

    Args:
        request (Request): JSON body with a boolean ``paused``.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: Updated cron payload or ``400`` when ``paused`` is missing.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(cron_config_put)
        True
    """

    body = await _read_json_object(request)
    paused = body.get("paused")
    if not isinstance(paused, bool):
        return _error_response("invalid_body", "body.paused must be a boolean", status_code=400)
    layout: WorkspaceLayout = request.app.state.layout
    sevn_json = layout.sevn_json_path
    on_disk = json.loads(sevn_json.read_text(encoding="utf-8"))
    triggers = dict(on_disk.get("triggers") or {})
    triggers["paused"] = paused
    try:
        validated = TriggersWorkspaceConfig.model_validate(triggers)
    except ValidationError as exc:
        return _validation_error_response(exc)
    on_disk["triggers"] = validated.model_dump(mode="python", exclude_none=True)
    try:
        validate_workspace_document(on_disk)
        write_draft(sevn_json, on_disk)
        promote_draft(sevn_json, backup_previous=True)
    except (ValidationError, ValueError, OSError) as exc:
        return _validation_error_response(exc)
    ws = WorkspaceConfig.model_validate(on_disk)
    request.app.state.workspace = ws
    return JSONResponse(status_code=200, content=_cron_payload(request.app.state.sqlite_conn, ws))


@router.get("/security")
async def security_get(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return ``security.*`` toggles for the Security tab.

    Args:
        request (Request): FastAPI request with workspace on ``app.state``.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Security subtree projection.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(security_get)
        True
    """

    ws: WorkspaceConfig = request.app.state.workspace
    return _security_payload(ws)


@router.put("/security")
async def security_put(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Patch ``security.*`` in ``sevn.json`` from a partial body.

    Args:
        request (Request): JSON body with optional ``security`` object.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: ``200`` with updated security projection or ``422`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(security_put)
        True
    """

    body = await _read_json_object(request)
    patch = body.get("security")
    if not isinstance(patch, dict):
        return _error_response(
            "invalid_body",
            "body.security must be a JSON object",
            status_code=400,
        )
    layout: WorkspaceLayout = request.app.state.layout
    sevn_json = layout.sevn_json_path
    on_disk = json.loads(sevn_json.read_text(encoding="utf-8"))
    merged_security = dict(on_disk.get("security") or {})
    merged_security.update(patch)
    try:
        validated = SecurityWorkspaceConfig.model_validate(merged_security)
    except ValidationError as exc:
        return _validation_error_response(exc)
    on_disk["security"] = validated.model_dump(mode="python", exclude_none=True)
    try:
        validate_workspace_document(on_disk)
        write_draft(sevn_json, on_disk)
        promote_draft(sevn_json, backup_previous=True)
    except (ValidationError, ValueError, OSError) as exc:
        return _validation_error_response(exc)
    ws = WorkspaceConfig.model_validate(on_disk)
    request.app.state.workspace = ws
    return JSONResponse(status_code=200, content=_security_payload(ws))


def _logfire_payload(ws: WorkspaceConfig) -> dict[str, object]:
    """Project Logfire export status for dashboard JSON responses.

    Args:
        ws (WorkspaceConfig): Parsed workspace configuration.

    Returns:
        dict[str, object]: Logfire export summary without secret values.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _logfire_payload(WorkspaceConfig.minimal())["enabled"]
        False
    """
    status = logfire_export_status(ws)
    return {
        "enabled": status.enabled,
        "token_ref": status.token_ref,
        "project": status.project,
        "local_sinks": list(status.local_sinks),
        "default_token_ref": DEFAULT_LOGFIRE_TOKEN_REF,
        "secret_logical_key": LOGFIRE_SECRET_LOGICAL_KEY,
    }


@router.get("/tracing/logfire")
async def tracing_logfire_get(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return Logfire trace export status for Mission Control.

    Args:
        request (Request): FastAPI request with workspace on ``app.state``.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Logfire export projection.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(tracing_logfire_get)
        True
    """
    ws: WorkspaceConfig = request.app.state.workspace
    return _logfire_payload(ws)


@router.put("/tracing/logfire")
async def tracing_logfire_put(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Enable/disable Logfire export and optionally store a write token.

    Body fields:
        ``enabled`` (bool): Add or remove the ``logfire`` sink.
        ``token`` (str, optional): Store in the workspace secrets chain.
        ``token_ref`` (str, optional): Override ``tracing.sinks[].token_ref``.
        ``project`` (str, optional): Override ``project`` / service name.
        ``keep_local_sinks`` (bool, default true): Retain sqlite/jsonl sinks when enabling.

    Args:
        request (Request): JSON body with Logfire export fields.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: ``200`` with updated projection or ``422`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(tracing_logfire_put)
        True
    """
    body = await _read_json_object(request)
    enabled_raw = body.get("enabled")
    if not isinstance(enabled_raw, bool):
        return _error_response(
            "invalid_body",
            "body.enabled must be a boolean",
            status_code=400,
        )
    token = body.get("token")
    if token is not None and not isinstance(token, str):
        return _error_response(
            "invalid_body",
            "body.token must be a string when present",
            status_code=400,
        )
    token_ref = body.get("token_ref")
    if token_ref is not None and not isinstance(token_ref, str):
        return _error_response(
            "invalid_body",
            "body.token_ref must be a string when present",
            status_code=400,
        )
    project = body.get("project")
    if project is not None and not isinstance(project, str):
        return _error_response(
            "invalid_body",
            "body.project must be a string when present",
            status_code=400,
        )
    keep_local = body.get("keep_local_sinks", True)
    if not isinstance(keep_local, bool):
        return _error_response(
            "invalid_body",
            "body.keep_local_sinks must be a boolean when present",
            status_code=400,
        )

    layout: WorkspaceLayout = request.app.state.layout
    sevn_json = layout.sevn_json_path
    if isinstance(token, str) and token.strip():
        chain = secrets_chain_from_workspace(
            layout.content_root, request.app.state.workspace.secrets_backend
        )
        try:
            await chain.set(LOGFIRE_SECRET_LOGICAL_KEY, token.strip())
        except Exception as exc:
            return _error_response("secret_store_failed", str(exc), status_code=409)
        token_ref = token_ref or DEFAULT_LOGFIRE_TOKEN_REF

    on_disk = json.loads(sevn_json.read_text(encoding="utf-8"))
    apply_logfire_export_to_sevn_doc(
        on_disk,
        enabled=enabled_raw,
        token_ref=token_ref if isinstance(token_ref, str) else None,
        project=project if isinstance(project, str) else None,
        keep_local_sinks=keep_local,
    )
    try:
        validate_workspace_document(on_disk)
        write_draft(sevn_json, on_disk)
        promote_draft(sevn_json, backup_previous=True)
    except (ValidationError, ValueError, OSError) as exc:
        return _validation_error_response(exc)
    ws = WorkspaceConfig.model_validate(on_disk)
    request.app.state.workspace = ws
    await emit_mission_audit(
        request,
        kind="mission.tracing.logfire",
        alias=LOGFIRE_SECRET_LOGICAL_KEY if isinstance(token, str) and token.strip() else None,
        hub_type="mission.config.changed",
        extra={"enabled": enabled_raw},
    )
    return JSONResponse(status_code=200, content=_logfire_payload(ws))


@router.get("/secrets/aliases")
async def secrets_aliases(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return sorted secret alias keys referenced in ``sevn.json`` (no values).

    Args:
        request (Request): FastAPI request with layout.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Alias list with redacted placeholders only.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(secrets_aliases)
        True
    """

    layout: WorkspaceLayout = request.app.state.layout
    raw = json.loads(layout.sevn_json_path.read_text(encoding="utf-8"))
    keys: set[str] = set()
    _collect_secret_ref_logical_keys(raw, keys=keys)
    aliases = [
        {"logical_key": key, "present": "<redacted>", "source": "sevn.json"} for key in sorted(keys)
    ]
    return {"aliases": aliases, "count": len(aliases)}


async def _resolve_config_alias_secret(request: Request, logical_key: str) -> str:
    """Resolve one ``${SECRET:…}`` logical key via the workspace secrets chain.

    Args:
        request (Request): FastAPI request with layout and workspace.
        logical_key (str): Parsed logical key from a config secret ref.

    Returns:
        str: Plaintext secret value.

    Raises:
        HTTPException: 404 when unreferenced or unresolved; 409 when store locked.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_resolve_config_alias_secret)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    ws: WorkspaceConfig = request.app.state.workspace
    raw = json.loads(layout.sevn_json_path.read_text(encoding="utf-8"))
    keys: set[str] = set()
    _collect_secret_ref_logical_keys(raw, keys=keys)
    if logical_key not in keys:
        raise HTTPException(
            status_code=404, detail=f"alias {logical_key!r} not referenced in config"
        )

    chain = secrets_chain_from_workspace(layout.content_root, ws.secrets_backend)
    env_val = os.environ.get(logical_key, "").strip()
    if env_val:
        return env_val

    locked = False
    for backend in chain.backends:
        try:
            value = await backend.get(logical_key)
        except SecretsStoreCorruptError as exc:
            if is_encrypted_store_unlock_error(exc):
                locked = True
                continue
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if value is not None:
            return value

    if locked:
        raise HTTPException(status_code=409, detail="encrypted secrets store is locked")
    raise HTTPException(status_code=404, detail=f"alias {logical_key!r} could not be resolved")


@router.get("/secrets/aliases/{logical_key}/reveal", response_model=SecretRevealResponse)
async def secrets_alias_reveal(
    logical_key: str,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> SecretRevealResponse:
    """Reveal one ``${SECRET:…}`` config alias for the owner session (audited).

    Args:
        logical_key (str): Logical secret key referenced in ``sevn.json``.
        request (Request): FastAPI request.
        _claims (DashboardClaims): Verified dashboard owner.
        _csrf (None): CSRF guard.

    Returns:
        SecretRevealResponse: Alias and plaintext.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(secrets_alias_reveal)
        True
    """
    value = await _resolve_config_alias_secret(request, logical_key)
    await emit_mission_audit(
        request,
        kind="mission.secrets.read",
        alias=logical_key,
        hub_type="mission.secrets.changed",
        extra={"source": "config_alias"},
    )
    return SecretRevealResponse(alias=logical_key, plaintext=value)


@router.get("/tunnels/status")
async def tunnels_status(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return tunnel mode, gateway bind, and lightweight doctor probes.

    Args:
        request (Request): FastAPI request with workspace and layout.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Infrastructure summary and probe rows.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(tunnels_status)
        True
    """

    layout: WorkspaceLayout = request.app.state.layout
    ws = _tunnel_workspace_from_disk(request)
    merged_preview = json.loads(layout.sevn_json_path.read_text(encoding="utf-8"))
    tunnel_cfg = tunnel_cfg_from_workspace(ws)
    gw = ws.gateway
    probes: list[dict[str, object]] = []
    probes.append(
        _validation_check_row(
            await probe_secrets_backend(
                content_root=layout.content_root,
                section=ws.secrets_backend,
            ),
        ),
    )
    cfg_proxy = ws.proxy if isinstance(ws.proxy, dict) else None
    probes.append(
        _validation_check_row(
            await probe_llm_reachability(
                merged_preview=merged_preview,
                cfg_proxy=cfg_proxy,
            ),
        ),
    )
    extra = ws.model_extra or {}
    infra = extra.get("infrastructure") if isinstance(extra.get("infrastructure"), dict) else {}
    ts: TunnelStatus = await asyncio.to_thread(default_manager.status, tunnel_cfg)
    tunnel_mode = str(tunnel_cfg.get("mode") or "").strip() or "none"
    return {
        "tunnel_mode": tunnel_mode,
        "tunnel_active": tunnel_mode != "none",
        "tunnel_healthy": ts.healthy,
        "tunnel_pid": ts.pid,
        "public_base_url": ts.public_url,
        "gateway_host": (gw.host if gw and gw.host else None) or "127.0.0.1",
        "gateway_port": gw.port if gw else None,
        "infrastructure": infra if isinstance(infra, dict) else {},
        "tunnel": tunnel_cfg,
        "process": {
            "pid": ts.pid,
            "healthy": ts.healthy,
            "public_url": ts.public_url,
            "error": ts.error,
        },
        "probes": probes,
        "generated_at_ns": time.time_ns(),
    }


def _tunnel_workspace_from_disk(request: Request) -> WorkspaceConfig:
    """Load ``sevn.json`` from disk for tunnel routes without mutating gateway state.

    Mission Control keeps ``app.state.workspace`` from gateway boot; ``sevn tunnel setup``
    mutates ``sevn.json`` without restarting the process. Tunnel routes read a fresh
    workspace document so mode/credentials match disk, without ``apply_workspace`` side
    effects on read-only status polls.

    Args:
        request (Request): FastAPI request with layout.

    Returns:
        WorkspaceConfig: Freshly loaded workspace config.

    Examples:
        >>> _tunnel_workspace_from_disk.__name__
        '_tunnel_workspace_from_disk'
    """
    layout: WorkspaceLayout = request.app.state.layout
    ws, _layout = load_workspace(sevn_json=layout.sevn_json_path)
    return ws


def _tunnel_status_dict(ts: TunnelStatus) -> dict[str, object]:
    """Serialize a :class:`TunnelStatus` for JSON API responses.

    Args:
        ts (TunnelStatus): Live tunnel process snapshot.

    Returns:
        dict[str, object]: JSON-serializable tunnel status fields.

    Examples:
        >>> from sevn.infrastructure.tunnel_manager import TunnelStatus
        >>> _tunnel_status_dict(TunnelStatus(mode="none", pid=None, healthy=False, public_url=None, error=None))
        {'mode': 'none', 'pid': None, 'healthy': False, 'public_url': None, 'error': None}
    """
    return {
        "mode": ts.mode,
        "pid": ts.pid,
        "healthy": ts.healthy,
        "public_url": ts.public_url,
        "error": ts.error,
    }


@router.get("/tunnels/process")
async def tunnels_process(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return live tunnel process health (pid, healthy, public_url).

    Args:
        request (Request): FastAPI request with workspace.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Process snapshot from TunnelManager.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(tunnels_process)
        True
    """
    ws = _tunnel_workspace_from_disk(request)
    tunnel_cfg = tunnel_cfg_from_workspace(ws)
    ts = await asyncio.to_thread(default_manager.status, tunnel_cfg)
    return _tunnel_status_dict(ts)


@router.post("/tunnels/start")
async def tunnels_start(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Start the configured tunnel provider (confirm gate, owner+CSRF).

    Spawns a tunnel child process using ``infrastructure.tunnel`` config.
    Requires ``{"confirm": true}`` in the request body.

    Args:
        request (Request): FastAPI request.
        _claims (DashboardClaims): Verified dashboard owner.
        _csrf (None): CSRF guard.

    Returns:
        dict[str, object]: Process state after start attempt.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(tunnels_start)
        True
    """
    body = await _read_json_object(request)
    if not body.get("confirm"):
        return _error_response(
            "confirm_required",
            'Pass {"confirm": true} to start the tunnel',
            status_code=400,
        )
    ws = _tunnel_workspace_from_disk(request)
    layout: WorkspaceLayout = request.app.state.layout
    tunnel_cfg = tunnel_cfg_from_workspace(ws)
    try:
        runtime_cfg = await prepare_tunnel_runtime_cfg(
            tunnel_cfg,
            gateway_port=(ws.gateway.port if ws.gateway else None),
            content_root=layout.content_root,
            secrets_backend=ws.secrets_backend,
        )
        ts = await asyncio.to_thread(default_manager.start, runtime_cfg, confirm=True)
    except (RuntimeError, ValueError) as exc:
        return _error_response("tunnel_start_failed", str(exc), status_code=400)
    await emit_mission_audit(
        request,
        kind="mission.tunnels.start",
        hub_type="mission.tunnels.changed",
        extra={"pid": ts.pid},
    )
    payload = _tunnel_status_dict(ts)
    status_code = 200 if ts.healthy else 502
    return JSONResponse(content=payload, status_code=status_code)


@router.post("/tunnels/stop")
async def tunnels_stop(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Stop the configured tunnel provider (confirm gate, owner+CSRF).

    Terminates the running tunnel child process (SIGTERM, SIGKILL after 5 s).
    Requires ``{"confirm": true}`` in the request body.

    Args:
        request (Request): FastAPI request.
        _claims (DashboardClaims): Verified dashboard owner.
        _csrf (None): CSRF guard.

    Returns:
        dict[str, object]: Process state after stop attempt.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(tunnels_stop)
        True
    """
    body = await _read_json_object(request)
    if not body.get("confirm"):
        return _error_response(
            "confirm_required",
            'Pass {"confirm": true} to stop the tunnel',
            status_code=400,
        )
    ws = _tunnel_workspace_from_disk(request)
    tunnel_cfg = tunnel_cfg_from_workspace(ws)
    try:
        ts = await asyncio.to_thread(default_manager.stop, tunnel_cfg, confirm=True)
    except (RuntimeError, ValueError) as exc:
        return _error_response("tunnel_stop_failed", str(exc), status_code=400)
    await emit_mission_audit(
        request,
        kind="mission.tunnels.stop",
        hub_type="mission.tunnels.changed",
        extra={},
    )
    return JSONResponse(content=_tunnel_status_dict(ts))


@router.get("/mission/subagents")
async def mission_subagents_get(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return sub-agent counts, running rows, limits, and recent history (W6.2).

    Args:
        request (Request): FastAPI request with supervisor/registry on ``app.state``.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Snapshot payload for the Mission Control sub-agents panel.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(mission_subagents_get)
        True
    """
    return await fetch_subagents_mission_payload(request)


@router.post("/mission/subagents/{subagent_id}/kill")
async def mission_subagent_kill(
    request: Request,
    subagent_id: str,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, object]:
    """Kill one tracked sub-agent run via the process supervisor (W6.2, D13).

    Args:
        request (Request): FastAPI request.
        subagent_id (str): Short registry id.
        _claims (DashboardClaims): Verified dashboard owner.
        _csrf (None): CSRF guard.

    Returns:
        dict[str, object]: Kill outcome.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(mission_subagent_kill)
        True
    """
    result = await kill_subagent_mission(request, subagent_id)
    await emit_mission_audit(
        request,
        kind="mission.subagents.kill",
        hub_type="mission.subagents.changed",
        extra={"subagent_id": subagent_id, "killed": result.get("killed")},
    )
    return result


@router.post("/mission/subagents/kill_all")
async def mission_subagents_kill_all(
    request: Request,
    role: str | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, object]:
    """Kill all active level-1 sub-agents, optionally scoped to one role (W6.2, D13).

    Args:
        request (Request): FastAPI request.
        role (str | None): Optional ``triager``/``tier_b``/``tier_c``/``tier_d`` filter.
        _claims (DashboardClaims): Verified dashboard owner.
        _csrf (None): CSRF guard.

    Returns:
        dict[str, object]: Number of runs cancelled.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(mission_subagents_kill_all)
        True
    """
    result = await kill_all_subagents_mission(request, role=role)
    await emit_mission_audit(
        request,
        kind="mission.subagents.kill_all",
        hub_type="mission.subagents.changed",
        extra={"role": result.get("role"), "killed_count": result.get("killed_count")},
    )
    return result


@router.get("/backup/manifest")
async def backup_manifest(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return config backup files and sandbox snapshot inventory.

    Args:
        request (Request): FastAPI request with layout.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Backup and snapshot lists (paths only, no archive bytes).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(backup_manifest)
        True
    """

    layout: WorkspaceLayout = request.app.state.layout
    snap_root = snapshots_dir(layout)
    manifest_path = snap_root / "snapshot-manifest.json"
    manifest_body: dict[str, object] | None = None
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest_body = loaded
        except (OSError, json.JSONDecodeError):
            manifest_body = None
    return {
        "config_backups": _list_config_backups(layout.sevn_json_path),
        "snapshots_dir": str(snap_root),
        "snapshot_manifest_path": str(manifest_path),
        "snapshot_manifest": manifest_body,
        "snapshot_tarballs": _list_snapshot_tarballs(layout),
        "restore_hint": "Restore via CLI: sevn migrate / promote from sevn.json.vN backup",
    }


@router.get("/schema/ontology")
async def schema_ontology(
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return workspace JSON Schema metadata and read-only ontology index.

    Args:
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Schema title/version and specs index entries.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(schema_ontology)
        True
    """

    try:
        schema_doc = load_workspace_json_schema()
    except (OSError, json.JSONDecodeError, FileNotFoundError) as exc:
        return {
            "schema_available": False,
            "schema_error": str(exc),
            "ontology": _ontology_index_payload(),
        }
    return {
        "schema_available": True,
        "schema_title": schema_doc.get("title"),
        "schema_version": schema_doc.get("$schema") or schema_doc.get("version"),
        "property_count": len(schema_doc.get("properties", {}))
        if isinstance(schema_doc.get("properties"), dict)
        else 0,
        "schema_export_hint": "infra/sevn.schema.json",
        "ontology": _ontology_index_payload(),
    }


__all__ = [
    "backup_manifest",
    "config_full_get",
    "config_full_put",
    "config_full_validate",
    "config_get",
    "cron_config_put",
    "cron_jobs_list",
    "mission_subagent_kill",
    "mission_subagents_get",
    "mission_subagents_kill_all",
    "router",
    "schema_ontology",
    "secrets_alias_reveal",
    "secrets_aliases",
    "security_get",
    "security_put",
    "tunnels_process",
    "tunnels_start",
    "tunnels_status",
    "tunnels_stop",
]
