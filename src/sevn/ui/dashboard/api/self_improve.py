"""Dashboard self-improve REST router.

Module: sevn.ui.dashboard.api.self_improve
Depends: json, pathlib, fastapi, sevn.agent.tracing.redacting_sink, sevn.self_improve.jobs.store

Exports:
    CreateImproveJobBody — ``POST /self_improve/jobs`` request body.
    SelfImproveCycleBody — ``POST /self_improve/cycle`` confirm body.
    self_improve_jobs — list improve jobs for the active workspace.
    create_self_improve_job — enqueue one improve job (owner-only).
    self_improve_cycle — confirm-gated manual improve cycle trigger.
    self_improve_job_eval_report — redacted ``eval_report.json`` for one job.
    approve_self_improve_plan — HITL approval for spec-kit plan stage.
    self_improve_feedback — recent ``feedback_events`` + ``structured_feedback``.
    self_improve_trajectories — recent ``trajectory_fact`` rows.
    self_improve_rlm_training — read-only RLM config + job status summary.
    self_improve_experiments — experiment aggregates from improve jobs.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy, redact_attrs
from sevn.agent.tracing.sink_factory import trace_redaction_policy_for
from sevn.config.defaults import DEFAULT_RLM_C_D_BACKEND, DEFAULT_RLM_REPL_LIFETIME
from sevn.config.workspace_config import WorkspaceConfig
from sevn.self_improve.effective import effective_self_improve_enabled
from sevn.self_improve.jobs.store import (
    ImproveJobRow,
    fetch_job_row,
    list_recent_job_rows,
    requeue_after_plan_approval,
)
from sevn.self_improve.paths import job_bundle_dir
from sevn.self_improve.spec_kit_stage import mark_plan_approved
from sevn.self_improve.types import ImproveJobId, OwnerPrincipal
from sevn.ui.dashboard.api.deps import require_dashboard_csrf, require_dashboard_owner
from sevn.ui.dashboard.services.auth import DashboardClaims
from sevn.ui.dashboard.services.ops_control import confirm_token_valid, enqueue_self_improve_cycle
from sevn.workspace.layout import WorkspaceLayout

router = APIRouter(prefix="/self_improve", tags=["dashboard-self-improve"])

_FEEDBACK_LIMIT_DEFAULT = 50
_FEEDBACK_LIMIT_MAX = 200
_TRAJECTORY_LIMIT_DEFAULT = 50
_TRAJECTORY_LIMIT_MAX = 200
_EXPERIMENT_JOB_SCAN_MAX = 500


class CreateImproveJobBody(BaseModel):
    """``POST /self_improve/jobs`` request body."""

    experiment_id: str = Field(default="default", min_length=1)
    client_token: str | None = None


class SelfImproveCycleBody(BaseModel):
    """``POST /self_improve/cycle`` confirm-gated body."""

    confirm_token: str | None = None


def _redact_json_value(value: object, policy: TraceRedactionPolicy) -> object:
    """Recursively redact mapping leaves before JSON responses.

    Args:
        value (object): Arbitrary JSON-compatible value.
        policy (TraceRedactionPolicy): Workspace redaction rules.

    Returns:
        object: Redacted structure safe for dashboard clients.

    Examples:
        >>> policy = TraceRedactionPolicy.from_defaults()
        >>> out = _redact_json_value({"password": "secret"}, policy)
        >>> isinstance(out, dict) and out["password"] == "<redacted>"
        True
    """
    if isinstance(value, dict):
        return redact_attrs({str(k): v for k, v in value.items()}, policy)
    if isinstance(value, list):
        return [_redact_json_value(item, policy) for item in value]
    return value


def _job_row_dict(row: ImproveJobRow) -> dict[str, object]:
    """Serialise one :class:`ImproveJobRow` for JSON.

    Args:
        row (ImproveJobRow): Hydrated job row.

    Returns:
        dict[str, object]: JSON-safe mapping.

    Examples:
        >>> _job_row_dict(
        ...     ImproveJobRow("j", "w", "awaiting_review", "A", 1, None, None, "/r.json", None),
        ... )["state"]
        'awaiting_review'
    """
    return {
        "job_id": row.job_id,
        "workspace_id": row.workspace_id,
        "state": row.state,
        "preset": row.preset,
        "sampler_seed": row.sampler_seed,
        "correlation_id": row.correlation_id,
        "shortlist_path": row.shortlist_path,
        "eval_report_path": row.eval_report_path,
        "blocked_reason": row.blocked_reason,
    }


def _eval_report_passed(report_path: Path) -> bool | None:
    """Return whether an on-disk eval report passed, or ``None`` when absent/invalid.

    Args:
        report_path (Path): ``eval_report.json`` location.

    Returns:
        bool | None: ``True``/``False`` when readable; ``None`` on missing/invalid files.

    Examples:
        >>> _eval_report_passed.__name__
        '_eval_report_passed'
    """
    if not report_path.is_file():
        return None
    try:
        payload = _load_eval_report_json(report_path)
    except (json.JSONDecodeError, TypeError, FileNotFoundError):
        return None
    return bool(payload.get("passed"))


def _load_eval_report_json(report_path: Path) -> dict[str, Any]:
    """Read and parse one on-disk eval report.

    Args:
        report_path (Path): ``eval_report.json`` location.

    Returns:
        dict[str, Any]: Parsed report body.

    Raises:
        FileNotFoundError: When the path is absent.
        json.JSONDecodeError: When the file is not valid JSON.

    Examples:
        >>> _load_eval_report_json.__name__
        '_load_eval_report_json'
    """
    if not report_path.is_file():
        msg = f"eval report missing: {report_path}"
        raise FileNotFoundError(msg)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = "eval report root must be an object"
        raise TypeError(msg)
    return payload


@router.get("/jobs")
async def self_improve_jobs(
    request: Request,
    limit: int | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """List recent improve jobs for the active workspace.

    Args:
        request (Request): FastAPI request with app state.
        limit (int | None): Optional page size (default 50, max 200).
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: ``items`` list of job summaries.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(self_improve_jobs)
        True
    """
    cap = 50 if limit is None else max(1, min(int(limit), 200))
    conn: sqlite3.Connection = request.app.state.sqlite_conn
    rows = list_recent_job_rows(conn, limit=cap)
    return {"items": [_job_row_dict(row) for row in rows]}


@router.post("/jobs")
async def create_self_improve_job(
    body: CreateImproveJobBody,
    request: Request,
    claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, object]:
    """Enqueue one improve job from Mission Control.

    Args:
        body (CreateImproveJobBody): Experiment id and optional dedupe token.
        request (Request): FastAPI request with app state.
        claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        dict[str, object]: ``job_id`` for the queued row.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(create_self_improve_job)
        True
    """
    enqueue = getattr(request.app.state, "enqueue_improve_job", None)
    if enqueue is None:
        raise HTTPException(status_code=503, detail="self_improve_unavailable")
    workspace: WorkspaceConfig = request.app.state.workspace
    layout: WorkspaceLayout = request.app.state.layout
    workspace_id = workspace.workspace_root or str(layout.content_root)
    principal = OwnerPrincipal(principal_kind="owner", principal_id=claims.sub)
    job_id = await enqueue(
        workspace_id=workspace_id,
        experiment_id=body.experiment_id,
        trigger="manual",
        correlation_id=None,
        owner_principal=principal,
        client_token=body.client_token,
    )
    worker = getattr(request.app.state, "improve_job_worker", None)
    if worker is not None:
        worker.schedule()
    return {"job_id": str(job_id)}


@router.post("/cycle")
async def self_improve_cycle(
    body: SelfImproveCycleBody,
    request: Request,
    claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, object]:
    """Trigger one self-improve cycle (confirm-gated alias of manual enqueue).

    Args:
        body (SelfImproveCycleBody): Confirm token body.
        request (Request): FastAPI request with app state.
        claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        dict[str, object]: ``job_id`` when enqueued.

    Raises:
        HTTPException: ``400`` without confirm, ``503`` when unavailable.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(self_improve_cycle)
        True
    """
    if not confirm_token_valid(body.model_dump()):
        raise HTTPException(status_code=400, detail="confirm_token required")
    try:
        return await enqueue_self_improve_cycle(request, claims_sub=claims.sub)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/approve_plan")
async def approve_self_improve_plan(
    job_id: str,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, object]:
    """Approve a spec-kit plan and re-queue the job when HITL is required.

    Args:
        job_id (str): Improve job id.
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        dict[str, object]: Updated job summary.

    Raises:
        HTTPException: ``404`` when the job is missing or not awaiting plan review.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(approve_self_improve_plan)
        True
    """
    conn: sqlite3.Connection = request.app.state.sqlite_conn
    layout: WorkspaceLayout = request.app.state.layout
    row = fetch_job_row(conn, job_id=ImproveJobId(job_id))
    if row is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    if row.state != "awaiting_plan_review":
        raise HTTPException(status_code=409, detail="job_not_awaiting_plan_review")
    bundle = job_bundle_dir(layout, job_id)
    await asyncio.to_thread(mark_plan_approved, bundle)
    ok = await asyncio.to_thread(
        requeue_after_plan_approval,
        conn,
        job_id=ImproveJobId(job_id),
    )
    if not ok:
        raise HTTPException(status_code=409, detail="approve_failed")
    worker = getattr(request.app.state, "improve_job_worker", None)
    if worker is not None:
        worker.schedule()
    refreshed = fetch_job_row(conn, job_id=ImproveJobId(job_id))
    if refreshed is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    return {"job": _job_row_dict(refreshed)}


@router.get("/jobs/{job_id}/eval_report")
async def self_improve_job_eval_report(
    job_id: str,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return redacted ``eval_report.json`` for one improve job.

    Args:
        job_id (str): Target job primary key.
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Parsed eval report with redacted nested attrs.

    Raises:
        HTTPException: ``404`` when the job or report file is missing.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(self_improve_job_eval_report)
        True
    """
    workspace: WorkspaceConfig = request.app.state.workspace
    policy = trace_redaction_policy_for(workspace)
    conn: sqlite3.Connection = request.app.state.sqlite_conn
    row = fetch_job_row(conn, job_id=ImproveJobId(job_id))
    if row is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    if not row.eval_report_path:
        raise HTTPException(status_code=404, detail="eval_report_missing")
    report_path = Path(row.eval_report_path)
    try:
        payload = await asyncio.to_thread(_load_eval_report_json, report_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="eval_report_missing") from None
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="eval_report_invalid") from exc
    except TypeError as exc:
        raise HTTPException(status_code=500, detail="eval_report_invalid") from exc
    redacted = _redact_json_value(payload, policy)
    if not isinstance(redacted, dict):
        raise HTTPException(status_code=500, detail="eval_report_invalid")
    return {"job_id": job_id, "report": redacted}


def _cap_limit(limit: int | None, *, default: int, maximum: int) -> int:
    """Clamp a dashboard list ``limit`` query parameter.

    Args:
        limit (int | None): Caller-supplied limit.
        default (int): Default when omitted.
        maximum (int): Hard ceiling.

    Returns:
        int: Clamped limit in ``[1, maximum]``.

    Examples:
        >>> _cap_limit(None, default=50, maximum=200)
        50
        >>> _cap_limit(999, default=50, maximum=200)
        200
    """
    if limit is None:
        return default
    return max(1, min(int(limit), maximum))


def _preview_text(value: str, *, max_chars: int = 240) -> str:
    """Truncate free-text fields for dashboard tables.

    Args:
        value (str): Raw text.
        max_chars (int): Maximum returned length.

    Returns:
        str: Trimmed preview.

    Examples:
        >>> _preview_text("hello")
        'hello'
        >>> _preview_text("x" * 300, max_chars=10)
        'xxxxxxxxxx…'
    """
    trimmed = value.strip()
    if len(trimmed) <= max_chars:
        return trimmed
    return trimmed[:max_chars] + "…"


@router.get("/feedback")
async def self_improve_feedback(
    request: Request,
    limit: int | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """List recent operator feedback (events + structured rows).

    Args:
        request (Request): FastAPI request with app state.
        limit (int | None): Page size (default 50, max 200).
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: ``events`` and ``structured`` lists.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(self_improve_feedback)
        True
    """
    cap = _cap_limit(limit, default=_FEEDBACK_LIMIT_DEFAULT, maximum=_FEEDBACK_LIMIT_MAX)
    workspace: WorkspaceConfig = request.app.state.workspace
    policy = trace_redaction_policy_for(workspace)
    conn: sqlite3.Connection = request.app.state.sqlite_conn
    event_rows = conn.execute(
        """SELECT feedback_id, kind, target_turn_id, schema_version, payload_json, created_at
        FROM feedback_events ORDER BY created_at DESC LIMIT ?""",
        (cap,),
    ).fetchall()
    structured_rows = conn.execute(
        """SELECT feedback_id, target_turn_id, user_id, channel, body_text,
            dropdowns_json, created_at
        FROM structured_feedback ORDER BY created_at DESC LIMIT ?""",
        (cap,),
    ).fetchall()
    events: list[dict[str, object]] = []
    for row in event_rows:
        try:
            payload_raw = json.loads(str(row[4]))
        except json.JSONDecodeError:
            payload_raw = {}
        if not isinstance(payload_raw, dict):
            payload_raw = {}
        redacted = _redact_json_value(payload_raw, policy)
        payload_out = redacted if isinstance(redacted, dict) else {}
        events.append(
            {
                "feedback_id": str(row[0]),
                "kind": str(row[1]),
                "target_turn_id": str(row[2]),
                "schema_version": int(row[3]),
                "payload": payload_out,
                "created_at": str(row[5]),
            },
        )
    structured: list[dict[str, object]] = []
    for row in structured_rows:
        try:
            dropdowns_raw = json.loads(str(row[5]))
        except json.JSONDecodeError:
            dropdowns_raw = {}
        if not isinstance(dropdowns_raw, dict):
            dropdowns_raw = {}
        dropdowns_redacted = _redact_json_value(dropdowns_raw, policy)
        dropdowns_out = dropdowns_redacted if isinstance(dropdowns_redacted, dict) else {}
        structured.append(
            {
                "feedback_id": str(row[0]),
                "target_turn_id": str(row[1]),
                "user_id": str(row[2]),
                "channel": str(row[3]),
                "body_preview": _preview_text(str(row[4])),
                "dropdowns": dropdowns_out,
                "created_at": str(row[6]),
            },
        )
    return {"events": events, "structured": structured, "limit": cap}


@router.get("/trajectories")
async def self_improve_trajectories(
    request: Request,
    limit: int | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """List recent ``trajectory_fact`` rows for sampler / eval orientation.

    Args:
        request (Request): FastAPI request with app state.
        limit (int | None): Page size (default 50, max 200).
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: ``items`` trajectory summaries.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(self_improve_trajectories)
        True
    """
    cap = _cap_limit(limit, default=_TRAJECTORY_LIMIT_DEFAULT, maximum=_TRAJECTORY_LIMIT_MAX)
    conn: sqlite3.Connection = request.app.state.sqlite_conn
    rows = conn.execute(
        """SELECT turn_id, session_id, channel, intent, tier, budget_regime, model_id,
            signals_json, trace_span_id, created_at
        FROM trajectory_fact ORDER BY created_at DESC LIMIT ?""",
        (cap,),
    ).fetchall()
    items: list[dict[str, object]] = []
    for row in rows:
        try:
            signals_raw = json.loads(str(row[7]))
        except json.JSONDecodeError:
            signals_raw = {}
        if not isinstance(signals_raw, dict):
            signals_raw = {}
        items.append(
            {
                "turn_id": str(row[0]),
                "session_id": str(row[1]),
                "channel": str(row[2]),
                "intent": str(row[3]) if row[3] is not None else None,
                "tier": str(row[4]) if row[4] is not None else None,
                "budget_regime": str(row[5]) if row[5] is not None else None,
                "model_id": str(row[6]) if row[6] is not None else None,
                "signals": signals_raw,
                "trace_span_id": str(row[8]) if row[8] is not None else None,
                "created_at": str(row[9]),
            },
        )
    return {"items": items, "limit": cap}


@router.get("/rlm-training")
async def self_improve_rlm_training(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return read-only tier C/D RLM config and improve-job status summary.

    Args:
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: ``rlm``, ``self_improve``, and ``jobs`` blocks.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(self_improve_rlm_training)
        True
    """
    workspace: WorkspaceConfig = request.app.state.workspace
    conn: sqlite3.Connection = request.app.state.sqlite_conn
    rlm_block = workspace.rlm
    lambda_gate = None
    if workspace.executors is not None and workspace.executors.tier_cd is not None:
        lambda_gate = workspace.executors.tier_cd.lambda_rlm
    rlm_payload: dict[str, object] = {
        "c_d_backend": (
            rlm_block.c_d_backend if rlm_block is not None else DEFAULT_RLM_C_D_BACKEND
        ),
        "repl_lifetime": (
            rlm_block.repl_lifetime if rlm_block is not None else DEFAULT_RLM_REPL_LIFETIME
        ),
        "lambda_tool_allowlist": (
            list(rlm_block.lambda_tool_allowlist)
            if rlm_block is not None and rlm_block.lambda_tool_allowlist
            else []
        ),
    }
    if lambda_gate is not None:
        rlm_payload["tier_cd_lambda_rlm"] = lambda_gate.model_dump(mode="json")
    si_block = workspace.self_improve
    self_improve_payload: dict[str, object] = {
        "enabled": effective_self_improve_enabled(workspace),
        "preset": si_block.preset if si_block is not None else None,
        "eval_docker_required": (
            si_block.eval.docker_required
            if si_block is not None and si_block.eval is not None
            else None
        ),
    }
    state_rows = conn.execute(
        "SELECT state, COUNT(*) FROM self_improve_jobs GROUP BY state",
    ).fetchall()
    by_state = {str(row[0]): int(row[1]) for row in state_rows}
    recent = list_recent_job_rows(conn, limit=10)
    tier_rows = conn.execute(
        """SELECT tier, COUNT(*) FROM trajectory_fact
        WHERE tier IS NOT NULL GROUP BY tier""",
    ).fetchall()
    return {
        "rlm": rlm_payload,
        "self_improve": self_improve_payload,
        "jobs": {
            "by_state": by_state,
            "recent": [_job_row_dict(row) for row in recent],
        },
        "trajectory_tier_counts": {str(row[0]): int(row[1]) for row in tier_rows},
        "read_only": True,
    }


@router.get("/experiments")
async def self_improve_experiments(
    request: Request,
    limit: int | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Aggregate improve jobs by ``experiment_id`` with eval outcomes when present.

    Args:
        request (Request): FastAPI request with app state.
        limit (int | None): Max experiment rows (default 50, max 200).
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: ``experiments`` summary list.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(self_improve_experiments)
        True
    """
    cap = _cap_limit(limit, default=_FEEDBACK_LIMIT_DEFAULT, maximum=_FEEDBACK_LIMIT_MAX)
    conn: sqlite3.Connection = request.app.state.sqlite_conn
    rows = conn.execute(
        """SELECT job_id, state, preset, experiment_snapshot_json, eval_report_path,
            started_at, finished_at
        FROM self_improve_jobs ORDER BY started_at DESC LIMIT ?""",
        (_EXPERIMENT_JOB_SCAN_MAX,),
    ).fetchall()
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        job_id = str(row[0])
        state = str(row[1])
        preset = str(row[2])
        experiment_id = "default"
        try:
            snap = json.loads(str(row[3]))
            if isinstance(snap, dict) and snap.get("experiment_id"):
                experiment_id = str(snap["experiment_id"])
        except json.JSONDecodeError:
            pass
        bucket = buckets.setdefault(
            experiment_id,
            {
                "experiment_id": experiment_id,
                "job_count": 0,
                "states": {},
                "latest_job_id": job_id,
                "latest_state": state,
                "latest_preset": preset,
                "eval_passed": None,
                "eval_failed": 0,
                "eval_passed_count": 0,
                "last_started_at": str(row[5]) if row[5] is not None else None,
            },
        )
        bucket["job_count"] = int(bucket["job_count"]) + 1
        states_raw = bucket["states"]
        states: dict[str, int] = states_raw if isinstance(states_raw, dict) else {}
        states[state] = int(states.get(state, 0)) + 1
        bucket["states"] = states
        eval_path = row[4]
        if eval_path:
            passed = await asyncio.to_thread(_eval_report_passed, Path(str(eval_path)))
            if passed is not None:
                if passed:
                    bucket["eval_passed_count"] = int(bucket["eval_passed_count"]) + 1
                else:
                    bucket["eval_failed"] = int(bucket["eval_failed"]) + 1
                if bucket["eval_passed"] is None:
                    bucket["eval_passed"] = passed
    experiments = sorted(
        buckets.values(),
        key=lambda item: str(item.get("last_started_at") or ""),
        reverse=True,
    )[:cap]
    return {"experiments": experiments, "limit": cap}


__all__ = [
    "CreateImproveJobBody",
    "SelfImproveCycleBody",
    "approve_self_improve_plan",
    "create_self_improve_job",
    "self_improve_cycle",
    "self_improve_experiments",
    "self_improve_feedback",
    "self_improve_job_eval_report",
    "self_improve_jobs",
    "self_improve_rlm_training",
    "self_improve_trajectories",
]
