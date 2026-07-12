"""Mission Control operations control-plane API (MC W3 §4).

Module: sevn.ui.dashboard.api.ops_control
Depends: pathlib, fastapi, pydantic, sevn.cli.service_manager, sevn.triggers.cron,
    sevn.ui.dashboard.api.deps, sevn.ui.dashboard.services.ops_control

Exports:
    ConfirmBody — confirm_token body for destructive ops.
    CronJobBody — cron job create/edit payload.
    ops_actions_capabilities — confirm model + action inventory.
    ops_daemons_status — gateway + proxy status.
    ops_reload_config — in-process sevn.json reload.
    ops_dreaming_run — trigger one dreaming cycle.
    ops_snapshot_create — create sandbox snapshot.
    ops_snapshot_restore — restore snapshot tarball.
    ops_backup_export — download config backup archive.
    ops_backup_import — upload config backup archive.
    cron_job_create — insert cron job row.
    cron_job_update — patch cron job row.
    cron_job_delete — delete cron job row.
    cron_job_run — trigger-now for one cron job.
    ops_daemon_action — install/enable/disable user units.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from sevn.cli.service_manager import ServiceManagerError
from sevn.triggers.cron import add_cron_job, delete_cron_job, edit_cron_job
from sevn.ui.dashboard.api.deps import require_dashboard_csrf, require_dashboard_owner
from sevn.ui.dashboard.services.auth import DashboardClaims
from sevn.ui.dashboard.services.mission_audit import emit_mission_audit
from sevn.ui.dashboard.services.ops_control import (
    OPS_CONFIRM_TOKEN,
    build_backup_export_bytes,
    build_daemons_status,
    confirm_token_valid,
    create_workspace_snapshot,
    cron_job_payload,
    daemon_control,
    dispatch_cron_job_now,
    import_backup_archive,
    list_bundled_skill_names,
    reload_workspace_in_process,
    restore_workspace_snapshot,
    run_dreaming_cycle,
)
from sevn.workspace.layout import WorkspaceLayout

router = APIRouter(tags=["dashboard-ops-control"])


class ConfirmBody(BaseModel):
    """Body with confirm token for destructive ops."""

    confirm_token: str | None = None


class CronJobBody(BaseModel):
    """Cron job create/edit payload."""

    job_id: str = Field(min_length=1)
    cron_expr: str = Field(min_length=1)
    timezone: str = "UTC"
    enabled: bool = True
    jitter_s: int = 0
    routing_mode: Literal["fixed", "auto_route"] = "fixed"
    delivery_mode: Literal["agent_pass", "notify_only"] = "agent_pass"
    permission_template_ref: str = "default"
    allow_tier_cd: bool = False
    overlap_policy: Literal["skip", "queue", "allow"] = "skip"
    result_channel_json: str = "{}"
    payload_template: str | None = None


def _error_response(
    code: str,
    message: str,
    *,
    status_code: int,
) -> JSONResponse:
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


def _require_confirm(body: dict[str, Any] | ConfirmBody) -> JSONResponse | None:
    """Return 400 when confirm token is missing on a destructive action.

    Args:
        body (dict[str, Any] | ConfirmBody): Parsed request body.

    Returns:
        JSONResponse | None: Error response or ``None`` when valid.

    Examples:
        >>> _require_confirm({"confirm_token": "confirm"}) is None
        True
    """
    payload = body if isinstance(body, dict) else body.model_dump()
    if confirm_token_valid(payload):
        return None
    return _error_response(
        "confirm_required",
        "destructive action requires confirm_token",
        status_code=400,
    )


@router.get("/ops/actions/capabilities")
async def ops_actions_capabilities(
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return ops confirm model and available control-plane actions.

    Args:
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Confirm token hint and action inventory.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(ops_actions_capabilities)
        True
    """
    return {
        "confirm_token": OPS_CONFIRM_TOKEN,
        "confirm_hint": "Include confirm_token in POST body for destructive/triggering ops",
        "actions": [
            "reload_config",
            "dreaming_run",
            "self_improve_cycle",
            "snapshot_create",
            "snapshot_restore",
            "backup_import",
            "cron_run",
            "cron_delete",
            "daemon_install",
            "daemon_enable",
            "daemon_disable",
            "skill_install",
            "skill_uninstall",
        ],
        "bundled_skills": list_bundled_skill_names(),
    }


@router.get("/ops/daemons")
async def ops_daemons_status(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return gateway + proxy daemon status (doctor-style probes).

    Args:
        request (Request): FastAPI request with workspace on app state.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Per-service listen and unit status.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(ops_daemons_status)
        True
    """
    ws = request.app.state.workspace
    try:
        return build_daemons_status(workspace=ws, home=Path.home())
    except Exception as exc:
        return {
            "gateway": {
                "listen_state": "unknown",
                "unit_installed": False,
                "unit_active": False,
                "health": {"listen_state": "unknown", "detail": str(exc)},
            },
            "proxy": {
                "listen_state": "unknown",
                "unit_installed": False,
                "unit_active": False,
                "health": {
                    "configured": False,
                    "ok": False,
                    "status_code": None,
                    "detail": str(exc),
                },
            },
            "generated_at_ns": time.time_ns(),
            "degraded": True,
        }


@router.post("/ops/reload-config")
async def ops_reload_config(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Reload ``sevn.json`` into the running gateway when supported.

    Args:
        request (Request): FastAPI request.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified CSRF token.

    Returns:
        JSONResponse: ``200`` on reload or ``409`` when restart is required.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(ops_reload_config)
        True
    """
    result = await reload_workspace_in_process(request)
    if result.get("status") == "restart_required":
        return JSONResponse(status_code=409, content=result)
    return JSONResponse(status_code=200, content=result)


@router.post("/ops/dreaming/run")
async def ops_dreaming_run(
    request: Request,
    body: ConfirmBody,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Trigger one dreaming cycle (confirm-gated).

    Args:
        request (Request): FastAPI request.
        body (ConfirmBody): Confirm token body.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified CSRF token.

    Returns:
        JSONResponse: Run outcome or structured error.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(ops_dreaming_run)
        True
    """
    denied = _require_confirm(body)
    if denied is not None:
        return denied
    try:
        result = await run_dreaming_cycle(request)
    except ValueError as exc:
        return _error_response("dreaming_unavailable", str(exc), status_code=503)
    return JSONResponse(status_code=200, content=result)


@router.post("/ops/snapshots")
async def ops_snapshot_create(
    request: Request,
    body: ConfirmBody,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Create a sandbox workspace snapshot tarball (confirm-gated).

    Args:
        request (Request): FastAPI request.
        body (ConfirmBody): Confirm token body.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified CSRF token.

    Returns:
        JSONResponse: Snapshot metadata.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(ops_snapshot_create)
        True
    """
    denied = _require_confirm(body)
    if denied is not None:
        return denied
    result = create_workspace_snapshot(request)
    await emit_mission_audit(
        request,
        kind="mission.ops.snapshot_create",
        op="snapshot_create",
        hub_type="mission.ops.changed",
        extra={"snapshot_id": result.get("snapshot_id")},
    )
    return JSONResponse(status_code=201, content=result)


@router.post("/ops/snapshots/{snapshot_id}/restore")
async def ops_snapshot_restore(
    snapshot_id: str,
    request: Request,
    body: ConfirmBody,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Restore workspace files from a snapshot tarball (confirm-gated).

    Args:
        snapshot_id (str): Snapshot basename under sandbox-snapshots.
        request (Request): FastAPI request.
        body (ConfirmBody): Confirm token body.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified CSRF token.

    Returns:
        JSONResponse: Restore summary or error.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(ops_snapshot_restore)
        True
    """
    denied = _require_confirm(body)
    if denied is not None:
        return denied
    try:
        result = restore_workspace_snapshot(request, snapshot_id=snapshot_id)
    except ValueError as exc:
        return _error_response("snapshot_restore_failed", str(exc), status_code=400)
    await emit_mission_audit(
        request,
        kind="mission.ops.snapshot_restore",
        op="snapshot_restore",
        hub_type="mission.ops.changed",
        extra={"snapshot_id": snapshot_id},
    )
    return JSONResponse(status_code=200, content=result)


@router.get("/ops/backup/export")
async def ops_backup_export(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> Response:
    """Download a tar.gz of ``sevn.json`` and versioned backups.

    Args:
        request (Request): FastAPI request with layout.
        _claims (DashboardClaims): Verified owner claims.

    Returns:
        Response: Gzip tarball attachment.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(ops_backup_export)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    data = build_backup_export_bytes(layout)
    return Response(
        content=data,
        media_type="application/gzip",
        headers={"Content-Disposition": 'attachment; filename="sevn-config-backup.tar.gz"'},
    )


@router.post("/ops/backup/import")
async def ops_backup_import(
    request: Request,
    archive: UploadFile = File(...),
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Import a config backup tarball (confirm-gated via form field).

    Args:
        request (Request): FastAPI request (multipart: archive + confirm_token).
        archive (UploadFile): Uploaded ``.tar.gz`` archive.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified CSRF token.

    Returns:
        JSONResponse: Import summary.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(ops_backup_import)
        True
    """
    form = await request.form()
    if not confirm_token_valid({"confirm_token": str(form.get("confirm_token", ""))}):
        return _error_response(
            "confirm_required",
            "destructive action requires confirm_token form field",
            status_code=400,
        )
    layout: WorkspaceLayout = request.app.state.layout
    raw = await archive.read()
    try:
        result = import_backup_archive(layout, raw)
    except ValueError as exc:
        return _error_response("backup_import_failed", str(exc), status_code=400)
    await emit_mission_audit(
        request,
        kind="mission.ops.backup_import",
        op="backup_import",
        hub_type="mission.ops.changed",
        extra={"imported": result.get("imported")},
    )
    return JSONResponse(status_code=200, content=result)


@router.post("/cron/jobs")
async def cron_job_create(
    request: Request,
    body: CronJobBody,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Create a cron job row in ``sevn.db``.

    Args:
        request (Request): FastAPI request.
        body (CronJobBody): New job definition.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified CSRF token.

    Returns:
        JSONResponse: Updated cron payload.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(cron_job_create)
        True
    """
    conn = request.app.state.sqlite_conn
    ws = request.app.state.workspace
    try:
        add_cron_job(
            conn,
            job_id=body.job_id,
            cron_expr=body.cron_expr,
            timezone=body.timezone,
            enabled=body.enabled,
            jitter_s=body.jitter_s,
            routing_mode=body.routing_mode,
            delivery_mode=body.delivery_mode,
            permission_template_ref=body.permission_template_ref,
            allow_tier_cd=body.allow_tier_cd,
            overlap_policy=body.overlap_policy,
            result_channel_json=body.result_channel_json,
            payload_template=body.payload_template,
        )
        conn.commit()
    except ValueError as exc:
        return _error_response("cron_invalid", str(exc), status_code=422)
    await emit_mission_audit(
        request,
        kind="mission.ops.cron_create",
        op="cron_create",
        hub_type="mission.ops.changed",
        extra={"job_id": body.job_id},
    )
    return JSONResponse(status_code=201, content=cron_job_payload(conn, ws))


@router.put("/cron/jobs/{job_id}")
async def cron_job_update(
    job_id: str,
    request: Request,
    body: CronJobBody,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Patch an existing cron job row.

    Args:
        job_id (str): Primary key.
        request (Request): FastAPI request.
        body (CronJobBody): Updated fields.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified CSRF token.

    Returns:
        JSONResponse: Updated cron payload.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(cron_job_update)
        True
    """
    conn = request.app.state.sqlite_conn
    ws = request.app.state.workspace
    try:
        edit_cron_job(
            conn,
            job_id=job_id,
            enabled=body.enabled,
            cron_expr=body.cron_expr,
            timezone=body.timezone,
            jitter_s=body.jitter_s,
            routing_mode=body.routing_mode,
            delivery_mode=body.delivery_mode,
            permission_template_ref=body.permission_template_ref,
            allow_tier_cd=body.allow_tier_cd,
            overlap_policy=body.overlap_policy,
            result_channel_json=body.result_channel_json,
            payload_template=body.payload_template,
            recompute_schedule=True,
        )
        conn.commit()
    except ValueError as exc:
        return _error_response("cron_invalid", str(exc), status_code=422)
    await emit_mission_audit(
        request,
        kind="mission.ops.cron_update",
        op="cron_update",
        hub_type="mission.ops.changed",
        extra={"job_id": job_id},
    )
    return JSONResponse(status_code=200, content=cron_job_payload(conn, ws))


@router.delete("/cron/jobs/{job_id}")
async def cron_job_delete(
    job_id: str,
    request: Request,
    body: ConfirmBody,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Delete a cron job row (confirm-gated).

    Args:
        job_id (str): Primary key.
        request (Request): FastAPI request.
        body (ConfirmBody): Confirm token body.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified CSRF token.

    Returns:
        JSONResponse: Updated cron payload or 404.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(cron_job_delete)
        True
    """
    denied = _require_confirm(body)
    if denied is not None:
        return denied
    conn = request.app.state.sqlite_conn
    ws = request.app.state.workspace
    if not delete_cron_job(conn, job_id):
        return _error_response("cron_not_found", f"job not found: {job_id}", status_code=404)
    conn.commit()
    await emit_mission_audit(
        request,
        kind="mission.ops.cron_delete",
        op="cron_delete",
        hub_type="mission.ops.changed",
        extra={"job_id": job_id},
    )
    return JSONResponse(status_code=200, content=cron_job_payload(conn, ws))


@router.post("/cron/jobs/{job_id}/run")
async def cron_job_run(
    job_id: str,
    request: Request,
    body: ConfirmBody,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Trigger one cron job immediately (confirm-gated).

    Args:
        job_id (str): Primary key.
        request (Request): FastAPI request.
        body (ConfirmBody): Confirm token body.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified CSRF token.

    Returns:
        JSONResponse: Dispatch correlation id.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(cron_job_run)
        True
    """
    denied = _require_confirm(body)
    if denied is not None:
        return denied
    try:
        result = await dispatch_cron_job_now(request, job_id=job_id)
    except ValueError as exc:
        code = "cron_not_found" if "not found" in str(exc) else "cron_dispatch_unavailable"
        status = 404 if code == "cron_not_found" else 503
        return _error_response(code, str(exc), status_code=status)
    return JSONResponse(status_code=200, content=result)


@router.post("/ops/daemons/{service}/{action}")
async def ops_daemon_action(
    service: Literal["gateway", "proxy"],
    action: Literal["install", "enable", "disable"],
    request: Request,
    body: ConfirmBody,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Install, enable, or disable gateway/proxy user units (confirm-gated).

    Args:
        service (Literal["gateway", "proxy"]): Target service.
        action (Literal["install", "enable", "disable"]): Daemon action.
        request (Request): FastAPI request.
        body (ConfirmBody): Confirm token body.
        _claims (DashboardClaims): Verified owner claims.
        _csrf (None): Verified CSRF token.

    Returns:
        JSONResponse: Action detail or service manager error.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(ops_daemon_action)
        True
    """
    denied = _require_confirm(body)
    if denied is not None:
        return denied
    try:
        result = daemon_control(home=Path.home(), service=service, action=action)
    except (ServiceManagerError, ValueError) as exc:
        return _error_response("daemon_action_failed", str(exc), status_code=502)
    await emit_mission_audit(
        request,
        kind="mission.ops.daemon",
        op=f"daemon_{action}",
        hub_type="mission.ops.changed",
        extra={"service": service, "action": action},
    )
    return JSONResponse(status_code=200, content=result)


__all__ = [
    "ConfirmBody",
    "CronJobBody",
    "cron_job_create",
    "cron_job_delete",
    "cron_job_run",
    "cron_job_update",
    "ops_actions_capabilities",
    "ops_backup_export",
    "ops_backup_import",
    "ops_daemon_action",
    "ops_daemons_status",
    "ops_dreaming_run",
    "ops_reload_config",
    "ops_snapshot_create",
    "ops_snapshot_restore",
    "router",
]
