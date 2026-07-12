"""Service façades for gateway and dashboard delegation (`specs/33-self-improvement.md` §2).

Module: sevn.self_improve.facade
Depends: asyncio, hashlib, json, sqlite3, zlib, sevn.config.defaults,
    sevn.config.workspace_config, sevn.self_improve.effective, sevn.self_improve.eval,
    sevn.self_improve.jobs.store, sevn.self_improve.paths, sevn.self_improve.retention,
    sevn.self_improve.trace_events, sevn.self_improve.types, sevn.workspace.layout

Exports:
    ensure_preset_c_auto_merge_allowed — preset C auto-merge eval gate.
    enqueue_improve_job — async queued job insert with guard rails.
    abort_improve_job — async operator kill switch transition.
    run_improve_job_eval — traced eval graph wrapper for job bundles.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import zlib
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Coroutine

from sevn.config.defaults import (
    DEFAULT_SELF_IMPROVE_EXPORT_TTL_DAYS,
    DEFAULT_SELF_IMPROVE_IMPROVE_ARTEFACT_RETENTION_DAYS,
    DEFAULT_SELF_IMPROVE_JOBS_MAX_CONCURRENT_WRITERS,
)
from sevn.runtime.background_tasks import spawn_logged
from sevn.self_improve.effective import effective_self_improve_enabled
from sevn.self_improve.eval import ImproveJobResult, eval_report_passed, run_docker_eval_graph
from sevn.self_improve.export import prune_stale_export_bundles, scaffold_improve_export_bundle
from sevn.self_improve.jobs.events import ImproveJobEventFanoutFn, maybe_publish_job_event
from sevn.self_improve.jobs.store import abort_job_row, enqueue_job_row
from sevn.self_improve.paths import improve_root, job_bundle_dir
from sevn.self_improve.retention import prune_stale_job_bundles
from sevn.self_improve.trace_events import emit_self_improve_trace

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from sevn.agent.tracing.sink import TraceSink
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.self_improve.types import ImproveJobId, OwnerPrincipal
    from sevn.workspace.layout import WorkspaceLayout


def _digest_payload(payload: object) -> str:
    """Return a stable SHA-256 hex digest for trace attrs.

    Args:
        payload (object): JSON-serializable value or raw bytes/text.

    Returns:
        str: Lowercase hex digest prefixed with ``sha256:``.

    Examples:
        >>> _digest_payload({"a": 1}).startswith("sha256:")
        True
    """
    if isinstance(payload, bytes):
        raw = payload
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _trace_job_attrs(
    *,
    job_id: str,
    sampler_seed: int,
    preset: str,
    experiment_id: str,
    correlation_id: str | None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build normative self-improve trace attrs (`specs/33-self-improvement.md` §7).

    Args:
        job_id (str): Improve job identifier.
        sampler_seed (int): Deterministic sampler seed for the job row.
        preset (str): Active preset label (``A`` / ``B`` / ``C``).
        experiment_id (str): Experiment identifier from the enqueue request.
        correlation_id (str | None): Optional upstream correlation id.
        extra (dict[str, object] | None): Additional attrs merged last.

    Returns:
        dict[str, object]: Attribute map for :func:`emit_self_improve_trace`.

    Examples:
        >>> attrs = _trace_job_attrs(
        ...     job_id="j1",
        ...     sampler_seed=1,
        ...     preset="A",
        ...     experiment_id="exp",
        ...     correlation_id=None,
        ... )
        >>> attrs["job_id"]
        'j1'
    """
    merged: dict[str, object] = {
        "job_id": job_id,
        "sampler_seed": sampler_seed,
        "preset": preset,
        "experiment_snapshot_id": experiment_id,
        "correlation_id": correlation_id or "",
    }
    if extra:
        merged.update(extra)
    return merged


def _schedule_trace_emit(coro: Coroutine[None, None, None]) -> None:
    """Run or schedule ``emit_self_improve_trace`` from sync façade helpers.

    Args:
        coro (Coroutine[None, None, None]): Awaitable from :func:`emit_self_improve_trace`.

    Returns:
        None: Always.

    Examples:
        >>> import asyncio
        >>> from sevn.agent.tracing.sink import NullTraceSink
        >>> from sevn.self_improve.trace_events import emit_self_improve_trace
        >>> _schedule_trace_emit(
        ...     emit_self_improve_trace(
        ...         NullTraceSink(), job_id="j", kind="self_improve.job_start",
        ...     ),
        ... ) is None
        True
    """
    spawn_logged(coro, label="self_improve_trace_emit")


def _active_writer_count(conn: sqlite3.Connection, *, workspace_id: str) -> int:
    """Count active writer-phase improve jobs scoped to ``workspace_id``.

    Args:
        conn (sqlite3.Connection): Gateway database connection with migrations applied.
        workspace_id (str): Partition key persisted on ``self_improve_jobs``.

    Returns:
        int: Row count snapshot for concurrency guardrails.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> cx = sqlite3.connect(":memory:")
        >>> apply_migrations(cx)
        >>> _active_writer_count(cx, workspace_id="unset")
        0
        >>> cx.close()
    """
    row = conn.execute(
        """SELECT COUNT(*) FROM self_improve_jobs
            WHERE workspace_id = ?
              AND state IN ('running', 'awaiting_eval', 'awaiting_review')""",
        (workspace_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def ensure_preset_c_auto_merge_allowed(
    *,
    workspace_config: WorkspaceConfig,
    eval_report_path: Path | None,
    trace_sink: TraceSink | None = None,
    job_id: str | None = None,
    sampler_seed: int | None = None,
    experiment_id: str | None = None,
    correlation_id: str | None = None,
) -> None:
    """Fail closed when preset **C** auto-merge is requested without a passing eval.

    Args:
        workspace_config (WorkspaceConfig): Parsed ``sevn.json``.
        eval_report_path (Path | None): On-disk ``eval_report.json`` for the job.
        trace_sink (TraceSink | None): Optional gateway trace sink for §7 spans.
        job_id (str | None): Improve job id when emitting ``promotion_blocked_eval``.
        sampler_seed (int | None): Sampler seed copied into trace attrs when present.
        experiment_id (str | None): Experiment id copied into trace attrs when present.
        correlation_id (str | None): Optional upstream correlation id for trace attrs.

    Raises:
        RuntimeError: When auto-merge is enabled but the eval did not pass.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> ws = WorkspaceConfig.minimal(
        ...     self_improve={"enabled": True, "preset": "A"},
        ... )
        >>> ensure_preset_c_auto_merge_allowed(workspace_config=ws, eval_report_path=None)
        >>> ws_c = WorkspaceConfig.minimal(
        ...     self_improve={
        ...         "enabled": True,
        ...         "preset": "C",
        ...         "auto_merge_enabled": True,
        ...         "hub": {"repo": "owner/repo"},
        ...     },
        ... )
        >>> try:
        ...     ensure_preset_c_auto_merge_allowed(
        ...         workspace_config=ws_c, eval_report_path=None
        ...     )
        ... except RuntimeError:
        ...     True
        ... else:
        ...     False
        True
    """
    si = workspace_config.self_improve
    if si is None or si.preset != "C" or not si.auto_merge_enabled:
        return
    if eval_report_path is None or not eval_report_passed(eval_report_path):
        if trace_sink is not None and job_id is not None:
            eval_digest = ""
            if eval_report_path is not None and eval_report_path.is_file():
                eval_digest = _digest_payload(eval_report_path.read_bytes())
            trace_attrs = _trace_job_attrs(
                job_id=job_id,
                sampler_seed=sampler_seed or 0,
                preset="C",
                experiment_id=experiment_id or "",
                correlation_id=correlation_id,
                extra={"eval_metrics_digest": eval_digest},
            )
            _schedule_trace_emit(
                emit_self_improve_trace(
                    trace_sink,
                    job_id=job_id,
                    kind="self_improve.promotion_blocked_eval",
                    status="blocked",
                    attrs=trace_attrs,
                ),
            )
        msg = "preset C auto-merge blocked until eval_report.json records passed=true"
        raise RuntimeError(msg)


async def run_improve_job_eval(
    *,
    workspace_config: WorkspaceConfig,
    layout: WorkspaceLayout,
    job_id: ImproveJobId,
    sampler_seed: int,
    experiment_id: str,
    correlation_id: str | None,
    trace_sink: TraceSink | None = None,
    repo_root: Path | None = None,
) -> ImproveJobResult:
    """Run the improve eval graph and emit per-segment trace spans.

    Args:
        workspace_config (WorkspaceConfig): Parsed ``sevn.json``.
        layout (WorkspaceLayout): Resolved filesystem layout for artefact paths.
        job_id (ImproveJobId): Target improve job identifier.
        sampler_seed (int): Deterministic sampler seed stored on the job row.
        experiment_id (str): Active experiment identifier.
        correlation_id (str | None): Optional upstream correlation id.
        trace_sink (TraceSink | None): Optional gateway trace sink for §7 spans.
        repo_root (Path | None): Optional repository checkout root for golden replay.

    Returns:
        ImproveJobResult: Aggregate eval graph outcome for job-store wiring.

    Examples:
        >>> run_improve_job_eval.__name__
        'run_improve_job_eval'
    """
    bundle = job_bundle_dir(layout, job_id)
    preset = workspace_config.self_improve.preset if workspace_config.self_improve else "A"
    base_attrs = _trace_job_attrs(
        job_id=str(job_id),
        sampler_seed=sampler_seed,
        preset=preset,
        experiment_id=experiment_id,
        correlation_id=correlation_id,
    )
    result = await asyncio.to_thread(
        run_docker_eval_graph,
        workspace=workspace_config,
        job_bundle=bundle,
        repo_root=repo_root,
    )
    for segment in result.segments:
        segment_attrs = {**base_attrs, "segment": segment.name}
        await emit_self_improve_trace(
            trace_sink,
            job_id=str(job_id),
            kind="self_improve.eval.segment_start",
            status="ok",
            attrs=segment_attrs,
        )
        segment_done_attrs = {
            **segment_attrs,
            "segment_status": segment.status,
            "segment_detail": segment.detail,
        }
        await emit_self_improve_trace(
            trace_sink,
            job_id=str(job_id),
            kind="self_improve.eval.segment_done",
            status=segment.status,
            attrs=segment_done_attrs,
        )
    return result


async def enqueue_improve_job(
    *,
    workspace_id: str,
    experiment_id: str,
    trigger: Literal["manual", "cron"],
    correlation_id: str | None,
    owner_principal: OwnerPrincipal,
    workspace_config: WorkspaceConfig,
    layout: WorkspaceLayout,
    sqlite_conn: sqlite3.Connection,
    client_token: str | None = None,
    job_event_fanout: ImproveJobEventFanoutFn | None = None,
    trace_sink: TraceSink | None = None,
    improve_job_worker: object | None = None,
) -> ImproveJobId:
    """Enqueue a new improve job after fail-closed policy checks.

    Additional ``sqlite_conn`` / ``layout`` / ``workspace_config`` parameters are
    runtime injection surfaces for the gateway — they are not duplicated in the
    product-facing shorthand in ``specs/33-self-improvement.md`` §2.2.

    Args:
        workspace_id (str): Logical scope identifier for the enqueue row.
        experiment_id (str): Active experiment identifier.
        trigger (Literal["manual", "cron"]): Ingress source label stored in snapshots.
        correlation_id (str | None): Optional upstream correlation id.
        owner_principal (OwnerPrincipal): Authenticated owner subject.
        workspace_config (WorkspaceConfig): Parsed ``sevn.json``.
        layout (WorkspaceLayout): Resolved filesystem layout for artefact paths.
        sqlite_conn (sqlite3.Connection): Shared gateway database handle.
        client_token (str | None): Optional idempotency token (``UNIQUE`` with workspace).
        job_event_fanout (ImproveJobEventFanoutFn | None): Optional lifecycle publisher.
        trace_sink (TraceSink | None): Optional gateway trace sink for §7 spans.
        improve_job_worker (object | None): Optional gateway worker; ``schedule()`` when set.

    Returns:
        ImproveJobId: Inserted or deduplicated identifier.

    Raises:
        RuntimeError: When disabled, writer limits exhausted, or config is missing.
        PermissionError: When the caller is not an owner principal.

    Examples:
        >>> import asyncio
        >>> import json
        >>> import sqlite3
        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> from sevn.config.workspace_config import parse_workspace_config
        >>> from sevn.self_improve.facade import enqueue_improve_job
        >>> from sevn.self_improve.types import OwnerPrincipal
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> def _demo_enqueue() -> str:
        ...     td = TemporaryDirectory()
        ...     root = Path(td.name)
        ...     _ = (root / "sevn.json").write_text(
        ...         json.dumps({"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}, "self_improve": {"enabled": True, "preset": "A"}}),
        ...         encoding="utf-8",
        ...     )
        ...     ws = parse_workspace_config(
        ...         {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}, "self_improve": {"enabled": True, "preset": "A"}},
        ...     )
        ...     ly = WorkspaceLayout(root / "sevn.json", root)
        ...     conn = sqlite3.connect(":memory:")
        ...     apply_migrations(conn)
        ...     oid = asyncio.run(
        ...         enqueue_improve_job(
        ...             workspace_id="ws",
        ...             experiment_id="e",
        ...             trigger="manual",
        ...             correlation_id=None,
        ...             owner_principal=OwnerPrincipal(
        ...                 principal_kind="owner", principal_id="me"
        ...             ),
        ...             workspace_config=ws,
        ...             layout=ly,
        ...             sqlite_conn=conn,
        ...             client_token="tok-demo",
        ...         ),
        ...     )
        ...     conn.close()
        ...     td.cleanup()
        ...     return str(oid)
        >>> jid = _demo_enqueue()
        >>> len(jid) == 32
        True
    """
    if owner_principal.get("principal_kind") != "owner":
        raise PermissionError("owner-only enqueue surface")
    if not effective_self_improve_enabled(workspace_config):
        raise RuntimeError("self_improve disabled via config or SEVN_DISABLE_SELF_IMPROVE")
    si = workspace_config.self_improve
    if si is None:
        msg = "self_improve config missing while effective enablement is true"
        raise RuntimeError(msg)
    export_enabled = si.export is not None and si.export.enabled
    export_ttl = (
        si.export.ttl_days
        if si.export is not None and si.export.ttl_days is not None
        else DEFAULT_SELF_IMPROVE_EXPORT_TTL_DAYS
    )

    max_writers = (
        si.jobs.max_concurrent_writers
        if si.jobs is not None
        else DEFAULT_SELF_IMPROVE_JOBS_MAX_CONCURRENT_WRITERS
    )

    def _precheck_and_seed() -> int:
        active = _active_writer_count(sqlite_conn, workspace_id=workspace_id)
        if active >= max_writers:
            msg = "self_improve jobs.max_concurrent_writers exhausted for workspace"
            raise RuntimeError(msg)
        return (
            zlib.adler32(f"{experiment_id}:{correlation_id or ''}:{trigger}".encode()) & 0x7FFFFFFF
        )

    seed = _precheck_and_seed()

    def _prune() -> None:
        root = improve_root(layout)
        prune_stale_job_bundles(
            root, retention_days=DEFAULT_SELF_IMPROVE_IMPROVE_ARTEFACT_RETENTION_DAYS
        )
        if export_enabled:
            exports_parent = root / "exports"
            prune_stale_export_bundles(exports_parent, retention_days=export_ttl)

    await asyncio.to_thread(_prune)

    def _enqueue() -> ImproveJobId:
        jid = enqueue_job_row(
            sqlite_conn,
            workspace_id=workspace_id,
            experiment_id=experiment_id,
            preset=si.preset,
            sampler_seed=seed,
            correlation_id=correlation_id,
            client_token=client_token,
            experiment_snapshot={
                "experiment_id": experiment_id,
                "trigger": trigger,
                "preset": si.preset,
            },
        )
        bundle = job_bundle_dir(layout, jid)
        bundle.mkdir(parents=True, exist_ok=True)
        sqlite_conn.execute(
            "UPDATE self_improve_jobs SET shortlist_path = ? WHERE job_id = ?",
            (str(bundle / "shortlist.json"), jid),
        )
        sqlite_conn.commit()
        return jid

    job_id = _enqueue()
    trace_attrs = _trace_job_attrs(
        job_id=str(job_id),
        sampler_seed=seed,
        preset=si.preset,
        experiment_id=experiment_id,
        correlation_id=correlation_id,
    )
    await emit_self_improve_trace(
        trace_sink,
        job_id=str(job_id),
        kind="self_improve.job_start",
        status="ok",
        attrs=trace_attrs,
    )
    shortlist_path = job_bundle_dir(layout, job_id) / "shortlist.json"
    shortlist_count = 0
    scores_digest = _digest_payload([])
    if shortlist_path.is_file():
        raw = shortlist_path.read_bytes()
        scores_digest = _digest_payload(raw)
        try:
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, list):
                shortlist_count = len(data)
            elif isinstance(data, dict):
                candidates = data.get("candidates")
                if isinstance(candidates, list):
                    shortlist_count = len(candidates)
        except json.JSONDecodeError:
            shortlist_count = 0
    await emit_self_improve_trace(
        trace_sink,
        job_id=str(job_id),
        kind="self_improve.shortlist_ready",
        status="ok",
        attrs={
            **trace_attrs,
            "shortlist_count": shortlist_count,
            "deterministic_scores_digest": scores_digest,
        },
    )
    if export_enabled:

        def _export_scaffold() -> None:
            bundle = job_bundle_dir(layout, job_id)
            eval_path = bundle / "eval_report.json"
            patch_dir = bundle / "patch"
            scaffold_improve_export_bundle(
                layout,
                str(job_id),
                eval_report_path=eval_path if eval_path.is_file() else None,
                patch_dir=patch_dir if patch_dir.is_dir() else None,
                ttl_days=export_ttl,
            )

        await asyncio.to_thread(_export_scaffold)
    await maybe_publish_job_event(
        job_event_fanout,
        payload={
            "job_id": str(job_id),
            "state": "queued",
            "event": "transition",
            "preset": si.preset,
            "correlation_id": correlation_id,
        },
    )
    if improve_job_worker is not None:
        schedule = getattr(improve_job_worker, "schedule", None)
        if callable(schedule):
            schedule()
    return job_id


async def abort_improve_job(
    job_id: ImproveJobId,
    *,
    owner_principal: OwnerPrincipal,
    sqlite_conn: sqlite3.Connection,
    job_event_fanout: ImproveJobEventFanoutFn | None = None,
) -> None:
    """Abort a running or queued job (operator kill switch).

    The ``sqlite_conn`` parameter mirrors the gateway-injected database handle used
    by ``enqueue_improve_job``.

    Args:
        job_id (ImproveJobId): Target job id.
        owner_principal (OwnerPrincipal): Authenticated owner subject.
        sqlite_conn (sqlite3.Connection): Shared gateway database handle.
        job_event_fanout (ImproveJobEventFanoutFn | None): Optional lifecycle publisher.
        improve_job_worker (object | None): Optional gateway worker; ``schedule()`` when set.

    Returns:
        None: Always when the abort statement succeeds (even if zero rows).

    Raises:
        PermissionError: When the caller is not an owner principal.

    Examples:
        >>> import asyncio
        >>> import json
        >>> import sqlite3
        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> from sevn.config.workspace_config import parse_workspace_config
        >>> from sevn.self_improve.facade import abort_improve_job, enqueue_improve_job
        >>> from sevn.self_improve.types import ImproveJobId, OwnerPrincipal
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> def _demo_abort() -> bool:
        ...     td = TemporaryDirectory()
        ...     root = Path(td.name)
        ...     _ = (root / "sevn.json").write_text(
        ...         json.dumps({"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}, "self_improve": {"enabled": True, "preset": "A"}}),
        ...         encoding="utf-8",
        ...     )
        ...     ws = parse_workspace_config(
        ...         {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}, "self_improve": {"enabled": True, "preset": "A"}},
        ...     )
        ...     ly = WorkspaceLayout(root / "sevn.json", root)
        ...     conn = sqlite3.connect(":memory:")
        ...     apply_migrations(conn)
        ...     principal = OwnerPrincipal(principal_kind="owner", principal_id="me")
        ...     async def _run() -> None:
        ...         jid = await enqueue_improve_job(
        ...             workspace_id="ws",
        ...             experiment_id="e",
        ...             trigger="manual",
        ...             correlation_id=None,
        ...             owner_principal=principal,
        ...             workspace_config=ws,
        ...             layout=ly,
        ...             sqlite_conn=conn,
        ...         )
        ...         await abort_improve_job(
        ...             ImproveJobId(jid), owner_principal=principal, sqlite_conn=conn
        ...         )
        ...     asyncio.run(_run())
        ...     conn.close()
        ...     td.cleanup()
        ...     return True
        >>> _demo_abort()
        True
    """
    if owner_principal.get("principal_kind") != "owner":
        raise PermissionError("owner-only abort surface")

    def _abort() -> tuple[bool, str]:
        row = sqlite_conn.execute(
            "SELECT preset FROM self_improve_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        preset = str(row[0]) if row else ""
        return abort_job_row(sqlite_conn, job_id=job_id), preset

    updated, preset = _abort()
    if updated:
        await maybe_publish_job_event(
            job_event_fanout,
            payload={
                "job_id": str(job_id),
                "state": "aborted",
                "event": "transition",
                "preset": preset,
            },
        )
