"""Dashboard system/admin REST router.

Module: sevn.ui.dashboard.api.system
Depends: httpx, fastapi, sevn.agent.harness, sevn.cli.service_manager, sevn.onboarding,
    sevn.security.secrets

Exports:
    budget_summary — budget scaffold endpoint.
    providers_health — live provider health probe endpoint.
    provider_oauth_reauth — OAuth re-auth handoff endpoint.
    proxy_status — proxy health probe endpoint.
    proxy_restart — proxy restart via service manager.
    proxy_logs — proxy log tail endpoint.
    system_logging_get — read logging retention settings.
    system_logging_put — update logging retention settings and sweep.
    upgrade_restart — schema upgrade + gateway restart composition.
    config_validate — config validation delegate.
    config_write — atomic config write delegate.
    migrate_preview — migration preview delegate.
    page_agent_intent — Page Agent intent endpoint.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from sevn.agent.harness.snapshots import (
    format_upgrade_paused_notification,
    pause_active_snapshots_for_upgrade,
    pending_resume_group_count,
)
from sevn.cli.service_manager import ServiceManagerError, control_unit
from sevn.config.errors import UnsupportedSchemaVersionError
from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import LoggingWorkspaceConfig, WorkspaceConfig
from sevn.logging.retention import effective_logging_config, sweep_rotated_service_logs
from sevn.onboarding.draft_store import write_draft
from sevn.onboarding.live_validate import (
    ValidationCheck,
    probe_llm_reachability,
    probe_secrets_backend,
)
from sevn.onboarding.migrate import describe_schema_upgrade, upgrade_schema_inplace
from sevn.onboarding.promote import promote_draft
from sevn.onboarding.validate import validate_workspace_document
from sevn.onboarding.wizard_credentials import credentials_status
from sevn.security.secrets import secrets_chain_from_workspace
from sevn.storage.paths import traces_sqlite_path
from sevn.ui.dashboard.api.deps import require_dashboard_csrf, require_dashboard_owner
from sevn.ui.dashboard.query import budget_summary_from_traces, ensure_trace_connection
from sevn.ui.dashboard.services.auth import DashboardClaims
from sevn.voice.backends import build_stt_backend, build_tts_backend
from sevn.voice.factory import voice_runtime_settings
from sevn.workspace.layout import WorkspaceLayout

router = APIRouter(tags=["dashboard-system"])

_LOG_REDACT = re.compile(
    r"(token|secret|password|api[_-]?key|credential|bearer)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_PROXY_LOG_TAIL_LINES = 200


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


def _validation_error_response(exc: Exception) -> JSONResponse:
    """Map validation failures to a dashboard **422** envelope.

    Args:
        exc (Exception): ``ValidationError`` or ``UnsupportedSchemaVersionError``.

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


def _origin(url: str) -> str:
    """Return URL origin without path/query.

    Args:
        url (str): Raw URL.

    Returns:
        str: ``scheme://host[:port]`` or empty string.

    Examples:
        >>> _origin("http://127.0.0.1:8787/healthz")
        'http://127.0.0.1:8787'
    """

    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _redact_log_line(line: str) -> str:
    """Redact obvious secret material from one log line.

    Args:
        line (str): Raw log line.

    Returns:
        str: Redacted line.

    Examples:
        >>> "token=abc" in _redact_log_line("token=abc123")
        False
    """

    return _LOG_REDACT.sub("<redacted>", line.rstrip("\n"))


def _tail_proxy_log(log_path: Path, *, max_lines: int) -> list[str]:
    """Return the last ``max_lines`` redacted lines from ``log_path`` when present.

    Args:
        log_path (Path): Proxy log file path.
        max_lines (int): Maximum lines to return.

    Returns:
        list[str]: Redacted tail lines (possibly empty).

    Examples:
        >>> _tail_proxy_log(Path("/nonexistent/proxy.log"), max_lines=5)
        []
    """

    if not log_path.is_file():
        return []
    try:
        raw = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    tail = raw[-max_lines:] if len(raw) > max_lines else raw
    return [_redact_log_line(line) for line in tail]


@router.get("/budget/summary")
async def budget_summary(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return budget rollups and subscription-window posture from traces.

    Args:
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Hourly rollups, per-regime totals, subscription windows.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(budget_summary)
        True
    """

    ly = request.app.state.layout
    conn = ensure_trace_connection(traces_sqlite_path(ly.dot_sevn))
    try:
        summary = budget_summary_from_traces(conn)
    finally:
        conn.close()

    alerts = summary.get("alerts")
    if isinstance(alerts, list) and alerts:
        hub = getattr(request.app.state, "dashboard_hub", None)
        if hub is not None:
            await hub.publish(
                "budget.alert", {"alerts": alerts, "projections": summary.get("projections")}
            )

    return summary


def _provider_health_row(
    *,
    provider_id: str,
    ok: bool,
    severity: str,
    detail: str,
) -> dict[str, object]:
    """Map one probe outcome to the dashboard providers-health row shape.

    Args:
        provider_id (str): Stable provider or probe identifier.
        ok (bool): Whether the probe succeeded.
        severity (str): ``info``, ``warn``, or ``error``.
        detail (str): Human-readable probe summary.

    Returns:
        dict[str, object]: One ``providers`` list element.

    Examples:
        >>> _provider_health_row(provider_id="x", ok=True, severity="info", detail="ok")["id"]
        'x'
    """

    return {"id": provider_id, "ok": ok, "severity": severity, "detail": detail}


def _validation_check_row(check: ValidationCheck) -> dict[str, object]:
    """Convert a live-validation probe row to a providers-health element.

    Args:
        check (ValidationCheck): Probe outcome from onboarding live validation.

    Returns:
        dict[str, object]: One ``providers`` list element.

    Examples:
        >>> from sevn.onboarding.live_validate import ValidationCheck
        >>> _validation_check_row(ValidationCheck("llm", True, "info", "ok"))["id"]
        'llm'
    """

    return _provider_health_row(
        provider_id=check.check_id,
        ok=check.ok,
        severity=check.severity,
        detail=check.detail,
    )


async def _probe_voice_backend(
    kind: str,
    tag: str,
    build_backend: Callable[[str], Any],
) -> dict[str, object]:
    """Probe one configured voice STT/TTS backend via ``is_available()``.

    Args:
        kind (str): ``stt`` or ``tts``.
        tag (str): Backend tag from ``voice.*_providers``.
        build_backend (Callable[[str], Any]): ``build_stt_backend`` or ``build_tts_backend``.

    Returns:
        dict[str, object]: One ``providers`` list element.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_probe_voice_backend)
        True
    """

    provider_id = f"voice_{kind}.{tag}"
    try:
        backend = build_backend(tag)
        ok = await backend.is_available()
    except Exception as exc:
        return _provider_health_row(
            provider_id=provider_id,
            ok=False,
            severity="warn",
            detail=str(exc),
        )
    return _provider_health_row(
        provider_id=provider_id,
        ok=ok,
        severity="info" if ok else "warn",
        detail="available" if ok else "backend unavailable",
    )


async def _collect_providers_health(
    *,
    layout: WorkspaceLayout,
    ws: WorkspaceConfig,
    merged_preview: dict[str, Any],
) -> list[dict[str, object]]:
    """Run live probes for proxy, secrets, credentials, and voice transports.

    Args:
        layout (WorkspaceLayout): Resolved workspace paths.
        ws (WorkspaceConfig): Parsed workspace document.
        merged_preview (dict[str, Any]): Raw ``sevn.json`` document for probe helpers.

    Returns:
        list[dict[str, object]]: Ordered provider health rows.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_collect_providers_health)
        True
    """

    rows: list[dict[str, object]] = []
    cfg_proxy = ws.proxy if isinstance(ws.proxy, dict) else None

    secrets_check = await probe_secrets_backend(
        content_root=layout.content_root,
        section=ws.secrets_backend,
    )
    rows.append(_validation_check_row(secrets_check))

    cred_status = await credentials_status(
        layout.content_root,
        section=ws.secrets_backend,
        config_doc=merged_preview,
    )
    present_raw = cred_status.get("present")
    present: dict[str, bool] = present_raw if isinstance(present_raw, dict) else {}

    from sevn.config.provider_secrets import (
        assigned_provider_names_from_doc,
        resolve_handoff_secret_alias,
    )

    assigned = sorted(assigned_provider_names_from_doc(merged_preview))
    provider_creds_ok = True
    for name in assigned:
        alias = resolve_handoff_secret_alias(merged_preview, name)
        ok = bool(present.get(alias))
        provider_creds_ok = provider_creds_ok and ok
        rows.append(
            _provider_health_row(
                provider_id=f"credential.{name}",
                ok=ok,
                severity="error" if not ok else "info",
                detail=(
                    f"{alias} present in secrets chain"
                    if ok
                    else f"{alias} missing from secrets chain"
                ),
            )
        )

    if not provider_creds_ok:
        rows.append(
            _provider_health_row(
                provider_id="llm_reachability",
                ok=False,
                severity="error",
                detail="one or more assigned provider credentials missing from secrets chain",
            )
        )
    elif assigned:
        llm_check = await probe_llm_reachability(
            merged_preview=merged_preview,
            cfg_proxy=cfg_proxy,
        )
        rows.append(_validation_check_row(llm_check))

    voice_settings = voice_runtime_settings(ws)
    for tag in voice_settings.stt_providers:
        rows.append(await _probe_voice_backend("stt", tag, build_stt_backend))
    for tag in voice_settings.tts_providers:
        rows.append(await _probe_voice_backend("tts", tag, build_tts_backend))

    return rows


@router.get("/providers/health")
async def providers_health(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return live provider health for Mission Control System / Providers panels.

    Args:
        request (Request): FastAPI request with workspace layout on ``app.state``.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: ``providers`` rows plus ``generated_at_ns``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(providers_health)
        True
    """

    layout: WorkspaceLayout = request.app.state.layout
    ws: WorkspaceConfig = request.app.state.workspace
    try:
        merged_preview = json.loads(layout.sevn_json_path.read_text(encoding="utf-8"))
        providers = await _collect_providers_health(
            layout=layout,
            ws=ws,
            merged_preview=merged_preview,
        )
    except Exception as exc:
        providers = [
            _provider_health_row(
                provider_id="health_probe",
                ok=False,
                severity="warn",
                detail=f"provider health probes unavailable: {exc}",
            )
        ]
    return {"providers": providers, "generated_at_ns": time.time_ns()}


@router.post("/providers/{provider_id}/oauth/reauth")
async def provider_oauth_reauth(
    provider_id: str,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Start provider OAuth re-auth via secrets backend probe + CLI handoff.

    Args:
        provider_id (str): Provider id path parameter.
        request (Request): FastAPI request with workspace layout.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: ``202`` handoff payload (never returns secret values).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(provider_oauth_reauth)
        True
    """

    ws = request.app.state.workspace
    layout = request.app.state.layout
    section = ws.secrets_backend if ws is not None else None
    chain = secrets_chain_from_workspace(layout.content_root, section)
    logical_key = f"oauth.{provider_id}"
    existing = await chain.get(logical_key)
    payload: dict[str, object] = {
        "status": "handoff",
        "provider_id": provider_id,
        "logical_key": logical_key,
        "has_existing_token": existing is not None,
        "cli_hint": f"sevn providers oauth login --provider {provider_id}",
    }
    if provider_id.strip().lower() == "openai":
        from sevn.security.oauth.authorize import build_authorization_flow

        flow = build_authorization_flow()
        payload["oauth_flow"] = "codex_pkce"
        payload["authorize_url"] = flow.authorize_url
    return JSONResponse(status_code=202, content=payload)


@router.get("/proxy/status")
async def proxy_status(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Probe configured proxy health.

    Args:
        request (Request): FastAPI request with process settings.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Proxy status with origin only, never credentials.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(proxy_status)
        True
    """

    process: ProcessSettings = request.app.state.process_settings
    if not process.proxy_url:
        return {"configured": False, "origin": "", "ok": False, "status_code": None}
    origin = _origin(process.proxy_url.rstrip("/"))
    probe_url = process.proxy_url.rstrip("/") + "/healthz"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(probe_url)
        return {
            "configured": True,
            "origin": origin,
            "ok": response.status_code < 400,
            "status_code": response.status_code,
        }
    except (httpx.HTTPError, OSError, ValueError):
        return {"configured": True, "origin": origin, "ok": False, "status_code": None}


@router.post("/proxy/restart")
async def proxy_restart(
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Restart the egress proxy user service unit.

    Args:
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: ``200`` on success or ``502`` when service manager fails.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(proxy_restart)
        True
    """

    try:
        line = control_unit(home=Path.home(), service="proxy", action="restart")
    except ServiceManagerError as exc:
        return _error_response(
            "proxy_restart_failed",
            str(exc),
            status_code=502,
        )
    return JSONResponse(status_code=200, content={"status": "ok", "detail": line})


@router.get("/proxy/logs")
async def proxy_logs(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> JSONResponse:
    """Return a redacted tail of ``logs/proxy.log`` under the workspace.

    Args:
        request (Request): FastAPI request with layout.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        JSONResponse: ``200`` with log lines (empty when the file is absent).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(proxy_logs)
        True
    """

    layout = request.app.state.layout
    log_path = layout.logs_dir / "proxy.log"
    lines = _tail_proxy_log(log_path, max_lines=_PROXY_LOG_TAIL_LINES)
    return JSONResponse(
        status_code=200,
        content={
            "path": str(log_path),
            "lines": lines,
            "truncated": len(lines) >= _PROXY_LOG_TAIL_LINES,
        },
    )


@router.post("/system/upgrade-restart")
async def upgrade_restart(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Apply optional schema upgrade, pause active runs, restart gateway.

    Args:
        request (Request): JSON body may include ``consent`` and ``apply_schema_upgrade``.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: ``200`` composition summary or ``502`` on upgrade/restart failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(upgrade_restart)
        True
    """

    body = await _read_json_object(request)
    consent = bool(body.get("consent", False))
    apply_schema = bool(body.get("apply_schema_upgrade", False))
    layout = request.app.state.layout
    workspace_dir = layout.sevn_json_path.parent
    schema_summary: dict[str, object] = {"changed": False}

    try:
        preview = describe_schema_upgrade(workspace_dir)
        schema_summary = dict(preview)
        if preview.get("changed") and apply_schema:
            if not consent:
                return _error_response(
                    "upgrade_consent_required",
                    "apply_schema_upgrade requires consent=true",
                    status_code=422,
                )
            applied = upgrade_schema_inplace(
                workspace_dir,
                consent=True,
                dry_run=False,
            )
            schema_summary["applied"] = applied
    except (UnsupportedSchemaVersionError, ValueError, OSError, FileNotFoundError) as exc:
        return _error_response("upgrade_failed", str(exc), status_code=502)

    conn = request.app.state.sqlite_conn
    paused = pause_active_snapshots_for_upgrade(conn)
    conn.commit()
    notification = format_upgrade_paused_notification(pending_resume_group_count(conn))

    try:
        restart_line = control_unit(home=Path.home(), service="gateway", action="restart")
    except ServiceManagerError as exc:
        return _error_response(
            "gateway_restart_failed",
            str(exc),
            status_code=502,
            details={"schema": schema_summary, "paused_runs": paused},
        )

    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "schema": schema_summary,
            "paused_runs": paused,
            "paused_notification": notification,
            "gateway_restart": restart_line,
        },
    )


@router.post("/config/validate")
async def config_validate(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Validate a candidate ``sevn.json`` document.

    Args:
        request (Request): JSON body is the candidate workspace document.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: ``200`` when valid or ``422`` on schema failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(config_validate)
        True
    """

    body = await _read_json_object(request)
    if not body:
        return _error_response(
            "invalid_body",
            "body must be a non-empty JSON object",
            status_code=400,
        )
    try:
        validate_workspace_document(body)
    except (ValidationError, UnsupportedSchemaVersionError, ValueError) as exc:
        return _validation_error_response(exc)
    return JSONResponse(status_code=200, content={"ok": True})


@router.put("/config")
async def config_write(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Validate and atomically promote a workspace document to ``sevn.json``.

    Args:
        request (Request): JSON body is the candidate workspace document.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: ``200`` on success or ``422`` on validation failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(config_write)
        True
    """

    body = await _read_json_object(request)
    if not body:
        return _error_response(
            "invalid_body",
            "body must be a non-empty JSON object",
            status_code=400,
        )
    layout = request.app.state.layout
    sevn_json = layout.sevn_json_path
    try:
        from sevn.onboarding.web_app import apply_model_slot_policy

        apply_model_slot_policy(body)
        validate_workspace_document(body)
        write_draft(sevn_json, body)
        promote_draft(sevn_json, backup_previous=sevn_json.is_file())
    except (ValidationError, UnsupportedSchemaVersionError, ValueError, OSError) as exc:
        return _validation_error_response(exc)
    return JSONResponse(
        status_code=200,
        content={"ok": True, "sevn_json": str(sevn_json)},
    )


@router.post("/migrate/preview")
async def migrate_preview(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Return a redactable schema-upgrade preview for the workspace ``sevn.json``.

    Args:
        request (Request): FastAPI request with layout.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: ``200`` preview payload (no secrets).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(migrate_preview)
        True
    """

    layout = request.app.state.layout
    workspace_dir = layout.sevn_json_path.parent
    try:
        preview = describe_schema_upgrade(workspace_dir)
    except (UnsupportedSchemaVersionError, ValueError, OSError, FileNotFoundError) as exc:
        return _validation_error_response(exc)
    return JSONResponse(status_code=200, content=preview)


@router.get("/system/logging")
async def system_logging_get(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> JSONResponse:
    """Return effective logging retention settings for Mission Control.

    Args:
        request (Request): FastAPI request with workspace on ``app.state``.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        JSONResponse: ``200`` with logging subtree fields.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(system_logging_get)
        True
    """
    ws = request.app.state.workspace
    cfg = effective_logging_config(ws)
    return JSONResponse(
        status_code=200,
        content={
            "retention_days": cfg.retention_days,
            "archive_mode": cfg.archive_mode,
            "archive_destination": cfg.archive_destination,
        },
    )


@router.put("/system/logging")
async def system_logging_put(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Update ``logging.*`` in ``sevn.json`` and run one retention sweep.

    Args:
        request (Request): FastAPI request with layout and workspace.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: ``200`` with updated settings and sweep counters.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(system_logging_put)
        True
    """
    body = await _read_json_object(request)
    layout = request.app.state.layout
    ws = request.app.state.workspace
    current = effective_logging_config(ws)
    merged = current.model_dump()
    merged.update(body)
    try:
        updated = LoggingWorkspaceConfig.model_validate(merged)
    except ValidationError as exc:
        return _validation_error_response(exc)
    if updated.archive_mode in ("r2", "gcs"):
        cloud = updated.cloud
        bucket_ref = None
        if updated.archive_mode == "r2" and cloud is not None and cloud.r2 is not None:
            bucket_ref = cloud.r2.bucket_ref
        if updated.archive_mode == "gcs" and cloud is not None and cloud.gcs is not None:
            bucket_ref = cloud.gcs.bucket_ref
        if not (bucket_ref or "").strip():
            return JSONResponse(
                status_code=422,
                content={"error": {"code": "validation_error", "message": "bucket_ref required"}},
            )
    sevn_json = layout.sevn_json_path
    on_disk = json.loads(sevn_json.read_text(encoding="utf-8"))
    on_disk["logging"] = updated.model_dump(exclude_none=True)
    validate_workspace_document(on_disk)
    write_draft(sevn_json, on_disk)
    promote_draft(sevn_json, backup_previous=True)
    ws.logging = updated
    sweep = sweep_rotated_service_logs(
        layout.logs_dir,
        content_root=layout.content_root,
        workspace=ws,
    )
    return JSONResponse(
        status_code=200,
        content={
            "retention_days": updated.retention_days,
            "archive_mode": updated.archive_mode,
            "archive_destination": updated.archive_destination,
            "sweep": {
                "scanned": sweep.scanned,
                "archived": sweep.archived,
                "skipped_cloud": sweep.skipped_cloud,
            },
        },
    )


@router.post("/page-agent/intent")
async def page_agent_intent(
    request: Request,
    claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Accept a Page Agent intent and return a structured acknowledgement.

    Args:
        request (Request): Starlette request (JSON body with ``intent`` text).
        claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: ``200`` with intent echo and routing hint, or ``403`` when disabled.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(page_agent_intent)
        True
    """
    ws = request.app.state.workspace
    page_cfg = ws.dashboard.page_agent if ws.dashboard is not None else None
    enabled = page_cfg.enabled if page_cfg is not None else False
    if not enabled:
        return JSONResponse(
            status_code=403,
            content={
                "error": "page_agent_disabled",
                "message": "Enable dashboard.page_agent.enabled in sevn.json",
            },
        )
    body = await _read_json_object(request)
    intent = str(body.get("intent", "")).strip()
    return JSONResponse(
        {
            "status": "accepted",
            "intent": intent,
            "owner": claims.sub,
            "routing_hint": "mission_control_page_agent_v2",
        },
    )
