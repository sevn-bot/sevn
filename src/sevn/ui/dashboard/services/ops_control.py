"""Mission Control operations control-plane helpers (MC W3 §4).

Module: sevn.ui.dashboard.services.ops_control
Depends: asyncio, json, shutil, tarfile, uuid, fastapi, sevn.cli.gateway_client,
    sevn.cli.install_gate, sevn.cli.service_manager, sevn.config.loader,
    sevn.onboarding.seed, sevn.security.sandbox_runtime, sevn.triggers.cron,
    sevn.triggers.request, sevn.ui.dashboard.services.mission_audit

Exports:
    confirm_token_valid — validate POST body confirm_token.
    build_daemons_status — gateway + proxy probe payload.
    reload_workspace_in_process — reload sevn.json when gateway_router is present.
    run_dreaming_cycle — trigger one dreaming pass via DreamingEngine.
    enqueue_self_improve_cycle — enqueue one improve job (manual trigger).
    create_workspace_snapshot — write sandbox snapshot tarball.
    restore_workspace_snapshot — extract supported tarball into workspace root.
    build_backup_export_bytes — tar.gz of sevn.json + versioned backups.
    import_backup_archive — restore sevn.json from uploaded archive bytes.
    dispatch_cron_job_now — fire one cron row through gateway dispatch hook.
    daemon_control — install/enable/disable gateway or proxy user units.
    list_bundled_skill_names — installable bundled skill directory names.
    install_bundled_skill — copy bundled skill into skills/user/.
    uninstall_user_skill — remove skills/user/<name>/ only.
    set_user_skill_quarantine — enable/disable user skill via quarantine flag.
    cron_job_payload — cron list response builder.
"""

from __future__ import annotations

import asyncio
import io
import json
import shutil
import tarfile
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sevn.cli.errors import CliPreconditionError
from sevn.cli.gateway_client import (
    probe_gateway_listen_state,
    probe_proxy_listen_state,
    proxy_healthz_get,
    resolve_proxy_base_url,
)
from sevn.cli.install_gate import install_daemon_plan
from sevn.cli.service_manager import (
    control_unit,
    install_paired_units,
    remove_paired_unit_files,
    stop_paired_units,
    unit_file_exists,
    unit_is_active,
)
from sevn.config.loader import load_workspace
from sevn.onboarding.seed import ensure_skills_user_dir
from sevn.security.sandbox_runtime import (
    _MANIFEST_NAME,
    snapshot_tarball_format_supported,
    snapshots_dir,
    write_workspace_snapshot_tarball,
)
from sevn.skills import SkillExecutionError
from sevn.skills.manager import SkillsManager
from sevn.triggers.cron import (
    SqliteCronStore,
    compute_next_fire_ns,
    cron_job_to_dict,
    list_cron_jobs,
)
from sevn.triggers.request import DispatchRequest, ResultChannel
from sevn.ui.dashboard.services.mission_audit import emit_mission_audit

if TYPE_CHECKING:
    from fastapi import Request

    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.workspace.layout import WorkspaceLayout

OPS_CONFIRM_TOKEN = "confirm"  # nosec B105

_BUNDLED_SKILLS_ROOT = Path(__file__).resolve().parents[3] / "data" / "bundled_skills" / "core"

DaemonService = Literal["gateway", "proxy"]
DaemonAction = Literal["install", "enable", "disable"]


def confirm_token_valid(body: dict[str, Any]) -> bool:
    """Return whether ``body.confirm_token`` matches the ops confirm literal.

    Args:
        body (dict[str, Any]): Parsed JSON POST body.

    Returns:
        bool: ``True`` when confirm token is present and valid.

    Examples:
        >>> confirm_token_valid({"confirm_token": "confirm"})
        True
        >>> confirm_token_valid({})
        False
    """
    return (body.get("confirm_token") or "").strip() == OPS_CONFIRM_TOKEN


def build_daemons_status(*, workspace: WorkspaceConfig, home: Path) -> dict[str, object]:
    """Build gateway + proxy status using doctor-style probes.

    Args:
        workspace (WorkspaceConfig): Active workspace config.
        home (Path): Operator home for unit file probes.

    Returns:
        dict[str, object]: Per-service listen state, unit presence, and healthz.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> payload = build_daemons_status(workspace=WorkspaceConfig.minimal(), home=Path("/tmp"))
        >>> "gateway" in payload and "proxy" in payload
        True
    """
    gw_listen = probe_gateway_listen_state(workspace=workspace)
    proxy_listen = probe_proxy_listen_state(workspace=workspace)
    proxy_origin = resolve_proxy_base_url(workspace=workspace)
    proxy_health: dict[str, object] = {
        "configured": bool(proxy_origin),
        "ok": False,
        "status_code": None,
    }
    if proxy_origin:
        try:
            resp = proxy_healthz_get(proxy_origin, liveness=True)
            proxy_health = {
                "configured": True,
                "ok": resp.status_code < 400,
                "status_code": resp.status_code,
            }
        except (CliPreconditionError, OSError, ValueError):
            proxy_health = {"configured": True, "ok": False, "status_code": None}

    def _service_row(service: DaemonService) -> dict[str, object]:
        return {
            "listen_state": gw_listen if service == "gateway" else proxy_listen,
            "unit_installed": unit_file_exists(home=home, service=service),
            "unit_active": unit_is_active(home=home, service=service),
        }

    return {
        "gateway": {**_service_row("gateway"), "health": {"listen_state": gw_listen}},
        "proxy": {**_service_row("proxy"), "health": proxy_health},
        "generated_at_ns": time.time_ns(),
    }


async def reload_workspace_in_process(request: Request) -> dict[str, object]:
    """Reload ``sevn.json`` into the running gateway when safe.

    Args:
        request (Request): FastAPI request with layout and optional gateway router.

    Returns:
        dict[str, object]: ``status`` ``ok`` or ``restart_required`` with detail.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(reload_workspace_in_process)
        True
    """
    router = getattr(request.app.state, "gateway_router", None)
    layout: WorkspaceLayout = request.app.state.layout
    if router is None or not hasattr(router, "apply_workspace"):
        return {
            "status": "restart_required",
            "detail": "in-process reload unavailable — restart the gateway daemon",
        }
    ws, _ = load_workspace(sevn_json=layout.sevn_json_path)
    request.app.state.workspace = ws
    router.apply_workspace(ws)
    await emit_mission_audit(
        request,
        kind="mission.ops.reload_config",
        op="reload_config",
        hub_type="mission.ops.changed",
        extra={"status": "ok"},
    )
    return {"status": "ok", "detail": "workspace config reloaded in-process"}


async def run_dreaming_cycle(request: Request) -> dict[str, object]:
    """Trigger one dreaming scheduled pass when the engine is available.

    Args:
        request (Request): FastAPI request with dreaming engine on app state.

    Returns:
        dict[str, object]: Outcome summary.

    Raises:
        ValueError: When dreaming engine is unavailable or disabled.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_dreaming_cycle)
        True
    """
    engine = getattr(request.app.state, "dreaming_engine", None)
    if engine is None:
        msg = "dreaming_engine unavailable — restart gateway or run via CLI"
        raise ValueError(msg)
    layout: WorkspaceLayout = request.app.state.layout
    ws: WorkspaceConfig = request.app.state.workspace
    result = await engine.run_scheduled(workspace_root=layout.content_root, ws=ws)
    await emit_mission_audit(
        request,
        kind="mission.ops.dreaming_run",
        op="dreaming_run",
        hub_type="mission.ops.changed",
        extra={"skipped": result is None},
    )
    return {"ok": True, "result": None if result is None else str(result)}


async def enqueue_self_improve_cycle(request: Request, *, claims_sub: str) -> dict[str, object]:
    """Enqueue one self-improve job (manual operator trigger).

    Args:
        request (Request): FastAPI request with enqueue hook on app state.
        claims_sub (str): Dashboard owner principal id.

    Returns:
        dict[str, object]: ``job_id`` when enqueued.

    Raises:
        ValueError: When self-improve is disabled or enqueue hook is missing.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(enqueue_self_improve_cycle)
        True
    """
    from sevn.self_improve.effective import effective_self_improve_enabled
    from sevn.self_improve.types import OwnerPrincipal

    enqueue = getattr(request.app.state, "enqueue_improve_job", None)
    if enqueue is None:
        msg = "self_improve_unavailable"
        raise ValueError(msg)
    ws: WorkspaceConfig = request.app.state.workspace
    if not effective_self_improve_enabled(ws):
        msg = "self_improve disabled in sevn.json"
        raise ValueError(msg)
    layout: WorkspaceLayout = request.app.state.layout
    workspace_id = ws.workspace_root or str(layout.content_root)
    principal = OwnerPrincipal(principal_kind="owner", principal_id=claims_sub)
    job_id = await enqueue(
        workspace_id=workspace_id,
        experiment_id="default",
        trigger="manual",
        correlation_id=None,
        owner_principal=principal,
        client_token=None,
    )
    worker = getattr(request.app.state, "improve_job_worker", None)
    if worker is not None:
        worker.schedule()
    await emit_mission_audit(
        request,
        kind="mission.ops.self_improve_cycle",
        op="self_improve_cycle",
        hub_type="mission.ops.changed",
        extra={"job_id": str(job_id)},
    )
    return {"ok": True, "job_id": str(job_id)}


def create_workspace_snapshot(request: Request) -> dict[str, object]:
    """Write a sandbox snapshot tarball for the active workspace.

    Args:
        request (Request): FastAPI request with layout on app state.

    Returns:
        dict[str, object]: Snapshot path and name metadata.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(create_workspace_snapshot)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    sink = getattr(request.app.state, "gateway_trace", None)
    path = write_workspace_snapshot_tarball(
        layout,
        workspace_root=layout.content_root,
        sink=sink,
    )
    return {"ok": True, "snapshot_id": path.name, "path": str(path)}


def _resolve_snapshot_path(layout: WorkspaceLayout, snapshot_id: str) -> Path:
    """Resolve a snapshot id to a confined tarball under the snapshots dir.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        snapshot_id (str): Basename or stem of a snapshot archive.

    Returns:
        Path: Resolved tarball path.

    Raises:
        ValueError: When id is invalid or path escapes snapshots dir.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> lay = WorkspaceLayout.from_config(
        ...     Path("/tmp/w/sevn.json"), WorkspaceConfig.minimal(),
        ... )
        >>> _resolve_snapshot_path(lay, "missing.tar.gz")  # doctest: +SKIP
        ...
    """
    raw = snapshot_id.strip()
    if not raw or "/" in raw or "\\" in raw or raw.startswith("."):
        msg = "invalid snapshot_id"
        raise ValueError(msg)
    name = raw if raw.endswith(".tar.gz") else f"{raw}.tar.gz"
    root = snapshots_dir(layout).resolve()
    candidate = (root / name).resolve()
    if not str(candidate).startswith(str(root)):
        msg = "snapshot path escapes snapshots dir"
        raise ValueError(msg)
    if not candidate.is_file():
        msg = f"snapshot not found: {name}"
        raise ValueError(msg)
    return candidate


def restore_workspace_snapshot(request: Request, *, snapshot_id: str) -> dict[str, object]:
    """Extract a supported snapshot tarball into the workspace content root.

    Args:
        request (Request): FastAPI request with layout on app state.
        snapshot_id (str): Snapshot basename under ``.sevn/sandbox-snapshots/``.

    Returns:
        dict[str, object]: Restore summary.

    Raises:
        ValueError: When format is unsupported or extraction is unsafe.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(restore_workspace_snapshot)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    tarball = _resolve_snapshot_path(layout, snapshot_id)
    if not snapshot_tarball_format_supported(tarball):
        msg = "unsupported snapshot format — take a fresh snapshot"
        raise ValueError(msg)
    root = layout.content_root.resolve()
    restored = 0
    with tarfile.open(tarball, mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.name == _MANIFEST_NAME or not member.isfile():
                continue
            rel = member.name.replace("\\", "/").lstrip("./")
            if not rel or rel.startswith("/") or ".." in Path(rel).parts:
                msg = f"unsafe archive member: {member.name}"
                raise ValueError(msg)
            dest = (root / rel).resolve()
            if not str(dest).startswith(str(root)):
                msg = f"unsafe archive member: {member.name}"
                raise ValueError(msg)
            dest.parent.mkdir(parents=True, exist_ok=True)
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            dest.write_bytes(extracted.read())
            restored += 1
    return {"ok": True, "snapshot_id": tarball.name, "files_restored": restored}


def build_backup_export_bytes(layout: WorkspaceLayout) -> bytes:
    """Build a tar.gz containing ``sevn.json`` and ``sevn.json.v*`` backups.

    Args:
        layout (WorkspaceLayout): Workspace layout.

    Returns:
        bytes: Gzip tarball bytes for download.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> lay = WorkspaceLayout.from_config(
        ...     Path("/tmp/w/sevn.json"), WorkspaceConfig.minimal(),
        ... )
        >>> isinstance(build_backup_export_bytes(lay), bytes)
        True
    """
    sevn_json = layout.sevn_json_path
    parent = sevn_json.parent
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        if sevn_json.is_file():
            tar.add(sevn_json, arcname=sevn_json.name)
        if parent.is_dir():
            for backup in sorted(parent.glob("sevn.json.v*")):
                if backup.is_file():
                    tar.add(backup, arcname=backup.name)
    return buf.getvalue()


def import_backup_archive(layout: WorkspaceLayout, data: bytes) -> dict[str, object]:
    """Restore ``sevn.json`` from an uploaded backup tarball.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        data (bytes): Gzip tarball bytes from :func:`build_backup_export_bytes`.

    Returns:
        dict[str, object]: Import summary.

    Raises:
        ValueError: When archive is invalid or lacks ``sevn.json``.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(import_backup_archive)
        True
    """
    if not data:
        msg = "empty backup archive"
        raise ValueError(msg)
    sevn_json = layout.sevn_json_path
    imported: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        names = {m.name for m in tar.getmembers() if m.isfile()}
        if "sevn.json" not in names:
            msg = "backup archive must contain sevn.json"
            raise ValueError(msg)
        for member in tar.getmembers():
            if not member.isfile():
                continue
            base = Path(member.name).name
            if base != "sevn.json" and not base.startswith("sevn.json.v"):
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            dest = sevn_json.parent / base
            dest.write_bytes(extracted.read())
            imported.append(base)
    return {"ok": True, "imported": imported}


async def dispatch_cron_job_now(request: Request, *, job_id: str) -> dict[str, object]:
    """Fire one cron job immediately through the gateway dispatch hook.

    Args:
        request (Request): FastAPI request with sqlite + dispatch hook.
        job_id (str): ``trigger_cron_jobs.job_id``.

    Returns:
        dict[str, object]: Dispatch correlation id and status.

    Raises:
        ValueError: When job is missing or dispatch hook is unavailable.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(dispatch_cron_job_now)
        True
    """
    conn = request.app.state.sqlite_conn
    store = SqliteCronStore(conn)
    row = store.get_job(job_id)
    if row is None:
        msg = f"cron job not found: {job_id}"
        raise ValueError(msg)
    dispatch_fn = getattr(request.app.state, "dispatch_trigger", None)
    if dispatch_fn is None:
        msg = "cron dispatch unavailable — restart gateway"
        raise ValueError(msg)
    try:
        rc_data = json.loads(row.result_channel_json)
        rc = ResultChannel.model_validate(rc_data)
    except Exception:
        rc = ResultChannel(kind="LOG")
    correlation_id = str(uuid.uuid4())
    prompt = row.payload_template or f"cron job {row.job_id}"
    req = DispatchRequest(
        prompt=prompt,
        routing_mode=row.routing_mode,
        delivery_mode=row.delivery_mode,
        permission_template_ref=row.permission_template_ref,
        allow_tier_cd=row.allow_tier_cd,
        result_channel=rc,
        correlation_id=correlation_id,
        trigger_meta={
            "transport": "cron",
            "cron_job_id": row.job_id,
            "overlap_policy": row.overlap_policy,
            "manual_trigger": True,
        },
        notify_template=row.payload_template if row.delivery_mode == "notify_only" else None,
    )
    trace = getattr(request.app.state, "gateway_trace", None)
    await asyncio.wait_for(dispatch_fn(req), timeout=600.0)
    nxt = compute_next_fire_ns(
        cron_expr=row.cron_expr,
        tz_name=row.timezone,
        from_ns=time.time_ns(),
    )
    store.update_schedule(
        job_id=row.job_id,
        next_fire_at_ns=nxt,
        last_correlation_id=correlation_id,
        last_status="ok",
    )
    conn.commit()
    await emit_mission_audit(
        request,
        kind="mission.ops.cron_run",
        op="cron_run",
        hub_type="mission.ops.changed",
        extra={"job_id": job_id, "correlation_id": correlation_id},
    )
    _ = trace
    return {"ok": True, "job_id": job_id, "correlation_id": correlation_id}


def daemon_control(
    *,
    home: Path,
    service: DaemonService,
    action: DaemonAction,
    dry_run: bool = False,
) -> dict[str, object]:
    """Install, enable (start), or disable (stop) a gateway/proxy user unit.

    Args:
        home (Path): Operator home directory.
        service (DaemonService): ``gateway`` or ``proxy``.
        action (DaemonAction): ``install``, ``enable``, or ``disable``.
        dry_run (bool, optional): Plan only. Defaults to False.

    Returns:
        dict[str, object]: Action outcome detail.

    Raises:
        ServiceManagerError: When platform install/control fails.
        ValueError: When action is unknown.

    Examples:
        >>> daemon_control(
        ...     home=Path("/tmp/h"), service="gateway", action="enable", dry_run=True
        ... )["service"]
        'gateway'
    """
    if action == "install":
        if service == "gateway":
            line = install_daemon_plan(dry_run=dry_run)
        else:
            plan = install_paired_units(home=home, dry_run=dry_run)
            line = f"proxy unit: {plan.proxy_unit_path}"
        return {"ok": True, "service": service, "action": action, "detail": line}
    if action == "enable":
        line = control_unit(home=home, service=service, action="start", dry_run=dry_run)
        return {"ok": True, "service": service, "action": action, "detail": line}
    if action == "disable":
        if dry_run:
            line = f"dry-run: stop {service}"
        else:
            stop_paired_units(home=home, dry_run=False)
            if service == "gateway":
                remove_paired_unit_files(home=home, dry_run=False)
            line = f"{service} stopped"
        return {"ok": True, "service": service, "action": action, "detail": line}
    msg = f"unknown daemon action: {action}"
    raise ValueError(msg)


def list_bundled_skill_names() -> list[str]:
    """Return sorted bundled skill directory names installable under ``skills/user/``.

    Returns:
        list[str]: Skill names with a ``SKILL.md`` in bundled core tree.

    Examples:
        >>> names = list_bundled_skill_names()
        >>> isinstance(names, list)
        True
    """
    if not _BUNDLED_SKILLS_ROOT.is_dir():
        return []
    names: list[str] = []
    for child in sorted(_BUNDLED_SKILLS_ROOT.iterdir()):
        if child.is_dir() and (child / "SKILL.md").is_file():
            names.append(child.name)
    return names


def install_bundled_skill(
    *,
    layout: WorkspaceLayout,
    skill_name: str,
    workspace: WorkspaceConfig,
) -> dict[str, object]:
    """Copy a bundled core skill into ``skills/user/<name>/``.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        skill_name (str): Bundled skill directory name.
        workspace (WorkspaceConfig): Active workspace config.

    Returns:
        dict[str, object]: Install summary.

    Raises:
        SkillExecutionError: When name is invalid or destination exists.
        ValueError: When bundled skill is missing.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(install_bundled_skill)
        True
    """
    name = skill_name.strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        msg = "invalid skill name"
        raise SkillExecutionError(msg, code="SKILL_VALIDATION")
    src = (_BUNDLED_SKILLS_ROOT / name).resolve()
    if not src.is_dir() or not (src / "SKILL.md").is_file():
        msg = f"bundled skill not found: {name}"
        raise ValueError(msg)
    if not str(src).startswith(str(_BUNDLED_SKILLS_ROOT.resolve())):
        msg = "bundled skill path confinement failed"
        raise ValueError(msg)
    user_root = ensure_skills_user_dir(layout.content_root)
    dst = (user_root / name).resolve()
    if not str(dst).startswith(str(user_root.resolve())):
        msg = "skills/user path confinement failed"
        raise ValueError(msg)
    if dst.exists():
        msg = f"user skill already exists: {name}"
        raise SkillExecutionError(msg, code="SKILL_VALIDATION")
    shutil.copytree(
        src,
        dst,
        ignore=lambda _dir, names: {name for name in names if name == "__pycache__"},
    )
    manager = SkillsManager.shared(layout.content_root, layout=layout, config=workspace)
    manager.reload()
    return {
        "ok": True,
        "skill_name": name,
        "path": str(dst),
        "registry_version": manager.registry_version,
    }


def uninstall_user_skill(
    *,
    layout: WorkspaceLayout,
    skill_name: str,
    workspace: WorkspaceConfig,
) -> dict[str, object]:
    """Remove ``skills/user/<name>/`` only (never ``skills/core/``).

    Args:
        layout (WorkspaceLayout): Workspace layout.
        skill_name (str): Flat user skill name.
        workspace (WorkspaceConfig): Active workspace config.

    Returns:
        dict[str, object]: Uninstall summary.

    Raises:
        SkillExecutionError: When skill is not under ``skills/user/``.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(uninstall_user_skill)
        True
    """
    name = skill_name.strip()
    if not name or "/" in name:
        msg = "uninstall accepts flat user skill names only"
        raise SkillExecutionError(msg, code="SKILL_VALIDATION")
    user_root = ensure_skills_user_dir(layout.content_root).resolve()
    target = (user_root / name).resolve()
    if not str(target).startswith(str(user_root)):
        msg = "skills/user path confinement failed"
        raise SkillExecutionError(msg, code="SKILL_VALIDATION")
    if "skills/core" in str(target):
        msg = "skills/core is read-only"
        raise SkillExecutionError(msg, code="SKILL_VALIDATION")
    if not target.is_dir():
        msg = f"user skill not found: {name}"
        raise SkillExecutionError(msg, code="SKILL_NOT_FOUND")
    shutil.rmtree(target)
    manager = SkillsManager.shared(layout.content_root, layout=layout, config=workspace)
    manager.reload()
    return {"ok": True, "skill_name": name, "registry_version": manager.registry_version}


def set_user_skill_quarantine(
    *,
    layout: WorkspaceLayout,
    skill_name: str,
    workspace: WorkspaceConfig,
    enabled: bool,
) -> dict[str, object]:
    """Toggle user-skill quarantine (enabled=False → quarantine on).

    Args:
        layout (WorkspaceLayout): Workspace layout.
        skill_name (str): Flat user skill name.
        workspace (WorkspaceConfig): Active workspace config.
        enabled (bool): When ``True``, clear quarantine; when ``False``, quarantine.

    Returns:
        dict[str, object]: Toggle summary.

    Raises:
        SkillExecutionError: When skill is not a user skill.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(set_user_skill_quarantine)
        True
    """
    import yaml

    from sevn.skills.manifest import split_frontmatter

    name = skill_name.strip()
    manager = SkillsManager.shared(layout.content_root, layout=layout, config=workspace)
    record = manager.get_record(name)
    if record.provenance not in {"user", "generated"}:
        msg = "enable/disable applies to user or generated skills only"
        raise SkillExecutionError(msg, code="SKILL_VALIDATION")
    md = record.skill_dir / "SKILL.md"
    if not md.is_file():
        msg = f"missing SKILL.md for {name}"
        raise SkillExecutionError(msg, code="SKILL_NOT_FOUND")
    raw = md.read_text(encoding="utf-8")
    fm, body = split_frontmatter(raw)
    mapping = yaml.safe_load(fm) or {}
    if not isinstance(mapping, dict):
        mapping = {}
    mapping["quarantine"] = not enabled
    new_fm = yaml.safe_dump(mapping, sort_keys=False, allow_unicode=True).rstrip() + "\n"
    md.write_text(f"---\n{new_fm}---\n{body}", encoding="utf-8")
    manager.reload()
    return {
        "ok": True,
        "skill_name": name,
        "enabled": enabled,
        "registry_version": manager.registry_version,
    }


def cron_job_payload(conn: Any, ws: WorkspaceConfig) -> dict[str, object]:
    """Build cron list payload for API responses.

    Args:
        conn (Any): SQLite connection.
        ws (WorkspaceConfig): Workspace config.

    Returns:
        dict[str, object]: Jobs list and paused flag.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(cron_job_payload)
        True
    """
    jobs = [cron_job_to_dict(job) for job in list_cron_jobs(conn)]
    paused = bool(ws.triggers and ws.triggers.paused)
    return {"jobs": jobs, "count": len(jobs), "triggers_paused": paused}


__all__ = [
    "OPS_CONFIRM_TOKEN",
    "build_backup_export_bytes",
    "build_daemons_status",
    "confirm_token_valid",
    "create_workspace_snapshot",
    "cron_job_payload",
    "daemon_control",
    "dispatch_cron_job_now",
    "enqueue_self_improve_cycle",
    "import_backup_archive",
    "install_bundled_skill",
    "list_bundled_skill_names",
    "reload_workspace_in_process",
    "restore_workspace_snapshot",
    "run_dreaming_cycle",
    "set_user_skill_quarantine",
    "uninstall_user_skill",
]
