"""Dashboard evolution REST router (`specs/35-bot-evolution.md` §2.8).

Module: sevn.ui.dashboard.api.evolution
Depends: fastapi, sevn.evolution.approvals, sevn.evolution.events, sevn.evolution.issues,
    sevn.evolution.pipeline_runner (lazy), sevn.evolution.pipelines, sevn.evolution.router,
    sevn.evolution.stats, sevn.ui.dashboard.query.traces

Exports:
    CreateEvolutionIssueBody — ``POST /evolution/issues`` request body.
    EditApprovalBody — ``POST /evolution/approvals/{id}/edit`` request body.
    ImportGithubIssueBody — ``POST /evolution/issues/import`` request body.
    RunPipelineBody — ``POST /evolution/pipelines/{id}/run`` request body.
    SyncGithubIssuesBody — ``POST /evolution/issues/sync`` request body.
    create_evolution_issue — create a local evolution issue.
    evolution_issue_import — import one GitHub issue by number.
    evolution_issue_sync — sync GitHub issues into the local registry.
    evolution_issues — list local evolution issues.
    evolution_issue_detail — fetch one issue by id.
    evolution_pipelines — list active pipeline runs.
    evolution_pipeline_detail — one pipeline with logs and stage stepper.
    evolution_pipeline_kill — cancel an active pipeline.
    evolution_pipeline_poll — manually refresh a Cursor Cloud issue by polling once.
    evolution_pipeline_run — manually trigger or resume a pipeline run.
    evolution_approvals — list HITL approval queue.
    evolution_approval_approve — approve one pending approval and enqueue resume.
    evolution_approval_reject — reject one pending approval.
    evolution_approval_edit — edit plan body and approve, then enqueue resume.
    evolution_traces — evolution/self-improve trace slice.
    evolution_stats — roll-up counters for Evolution tab.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from sevn.agent.tracing.sink_factory import trace_redaction_policy_for
from sevn.config.workspace_config import WorkspaceConfig
from sevn.evolution.approvals import (
    approval_to_api_dict,
    ensure_issue_approval,
    list_approvals,
    resolve_approval,
)
from sevn.evolution.events import EvolutionIssueEventPayload, maybe_publish_issue_event
from sevn.evolution.github_sync import import_github_issue, sync_github_issues
from sevn.evolution.issues import (
    create_issue,
    get_issue,
    issue_to_api_dict,
    list_issues,
    maybe_mirror_issue_to_github,
    my_sevn_repo_slug,
)
from sevn.evolution.pipelines import (
    get_pipeline_detail,
    kill_pipeline,
    list_active_pipelines,
)
from sevn.evolution.router import resolve_executor
from sevn.evolution.stats import compute_evolution_stats
from sevn.runtime.background_tasks import spawn_logged
from sevn.storage.paths import traces_sqlite_path
from sevn.ui.dashboard.api.deps import require_dashboard_csrf, require_dashboard_owner
from sevn.ui.dashboard.api.traces import _redact_trace_page
from sevn.ui.dashboard.query import clamp_limit, ensure_trace_connection, list_trace_events
from sevn.ui.dashboard.services.auth import DashboardClaims
from sevn.workspace.layout import WorkspaceLayout

router = APIRouter(prefix="/evolution", tags=["dashboard-evolution"])

_EVOLUTION_KIND_PREFIXES = ["evolution.", "self_improve."]


class CreateEvolutionIssueBody(BaseModel):
    """``POST /evolution/issues`` request body."""

    kind: str = Field(pattern="^(bug|feature)$")
    title: str = Field(min_length=1, max_length=500)
    body: str = ""


class EditApprovalBody(BaseModel):
    """``POST /evolution/approvals/{id}/edit`` request body."""

    body: str = Field(min_length=1)


class ImportGithubIssueBody(BaseModel):
    """``POST /evolution/issues/import`` request body."""

    number: int = Field(ge=1)


class SyncGithubIssuesBody(BaseModel):
    """``POST /evolution/issues/sync`` request body."""

    state: str = Field(default="open", pattern="^(open|closed|all)$")
    labels: list[str] | None = None


class RunPipelineBody(BaseModel):
    """``POST /evolution/pipelines/{issue_id}/run`` request body."""

    stage: Literal["auto", "plan", "implement", "ci", "promote"] = "auto"
    executor: Literal["local", "cursor_cloud", "chat"] | None = None
    live: bool = False
    """When ``True``, all three dry-run flags are set to ``False``."""


async def _publish_issue_event(request: Request, payload: EvolutionIssueEventPayload) -> None:
    """Fan out one evolution issue event when gateway hook is configured.

    Args:
        request (Request): FastAPI request with app state.
        payload (EvolutionIssueEventPayload): Event body.

    Returns:
        None: Side-effect only.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_publish_issue_event)
        True
    """
    fanout = getattr(request.app.state, "evolution_issue_event_fanout", None)
    await maybe_publish_issue_event(fanout, payload=payload)


def _enqueue_pipeline_resume(request: Request, issue_id: str) -> None:
    """Fire-and-forget ``run_pipeline`` on the running event loop (W0.1).

    Called after a successful approve / edit to advance the issue to
    ``implementing`` without blocking the approval HTTP response.  The task
    runs on the existing gateway event loop so it does not interfere with the
    serial poll loop.

    Args:
        request (Request): FastAPI request carrying app state (ws, layout, conn).
        issue_id (str): Issue id to resume.

    Returns:
        None: Always; scheduling errors are logged but not raised.

    Examples:
        >>> _enqueue_pipeline_resume.__name__
        '_enqueue_pipeline_resume'
    """
    try:
        from sevn.evolution.pipeline_runner import run_pipeline as _run_pipeline

        ws: WorkspaceConfig = request.app.state.workspace
        layout = request.app.state.layout
        conn: sqlite3.Connection = request.app.state.sqlite_conn
        fanout = getattr(request.app.state, "evolution_issue_event_fanout", None)
        spawn_logged(
            _run_pipeline(conn, ws, layout, issue_id, stage="implement", fanout=fanout),
            label="evolution_pipeline_resume",
        )
    except RuntimeError:
        # Not called from a running loop context — skip enqueue; operator must
        # trigger manually.  This branch is reachable only in sync test stubs.
        pass
    except Exception as exc:
        from loguru import logger

        logger.warning(f"_enqueue_pipeline_resume: failed to schedule {issue_id}: {exc}")


@router.get("/issues")
async def evolution_issues(
    request: Request,
    limit: int | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """List evolution issues for Mission Control.

    Args:
        request (Request): FastAPI request with app state.
        limit (int | None): Optional page size (default 50, max 200).
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: ``items`` list with executor badge fields.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(evolution_issues)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    cap = 50 if limit is None else max(1, min(int(limit), 200))
    items = [issue_to_api_dict(issue) for issue in list_issues(layout, limit=cap)]
    return {"items": items}


@router.get("/issues/{issue_id}")
async def evolution_issue_detail(
    issue_id: str,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, Any]:
    """Return one evolution issue including executor routing metadata.

    Args:
        issue_id (str): Issue id.
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, Any]: Issue payload.

    Raises:
        HTTPException: ``404`` when the issue file is missing.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(evolution_issue_detail)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    ws: WorkspaceConfig = request.app.state.workspace
    issue = get_issue(layout, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="issue_not_found")
    payload = issue_to_api_dict(issue)
    payload["configured_executor"] = resolve_executor(ws, issue.kind)
    return payload


@router.post("/issues")
async def create_evolution_issue(
    body: CreateEvolutionIssueBody,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, Any]:
    """Create a local evolution issue.

    Args:
        body (CreateEvolutionIssueBody): Kind, title, and body.
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        dict[str, Any]: Created issue payload.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(create_evolution_issue)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    ws: WorkspaceConfig = request.app.state.workspace
    issue = create_issue(
        layout,
        kind=body.kind,  # type: ignore[arg-type]
        title=body.title,
        body=body.body,
        source="mc",
        ws=ws,
    )
    issue = await maybe_mirror_issue_to_github(layout, issue, ws)
    payload = issue_to_api_dict(issue)
    payload["configured_executor"] = resolve_executor(ws, issue.kind)
    return payload


@router.post("/issues/import")
async def evolution_issue_import(
    body: ImportGithubIssueBody,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, Any]:
    """Import one GitHub issue by number into the local registry.

    Args:
        body (ImportGithubIssueBody): GitHub issue number to import.
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        dict[str, Any]: Imported (or updated) issue payload.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(evolution_issue_import)
        True
    """
    from sevn.integrations.github_skill import resolve_github_skill_hooks

    layout: WorkspaceLayout = request.app.state.layout
    ws: WorkspaceConfig = request.app.state.workspace
    hooks = resolve_github_skill_hooks(ws)
    issue = await import_github_issue(
        layout,
        hooks,
        repo=my_sevn_repo_slug(ws),
        number=body.number,
        ws=ws,
    )
    payload = issue_to_api_dict(issue)
    payload["configured_executor"] = resolve_executor(ws, issue.kind)
    return payload


@router.post("/issues/sync")
async def evolution_issue_sync(
    body: SyncGithubIssuesBody,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, Any]:
    """Sync GitHub issues into the local registry.

    Args:
        body (SyncGithubIssuesBody): Optional ``state`` and ``labels`` filter.
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        dict[str, Any]: Counters (``imported``/``updated``/``skipped``) and item ids.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(evolution_issue_sync)
        True
    """
    from sevn.integrations.github_skill import resolve_github_skill_hooks

    layout: WorkspaceLayout = request.app.state.layout
    ws: WorkspaceConfig = request.app.state.workspace
    hooks = resolve_github_skill_hooks(ws)
    result = await sync_github_issues(
        layout,
        hooks,
        repo=my_sevn_repo_slug(ws),
        ws=ws,
        state=body.state,
        labels=body.labels,
    )
    items = result.issues or []
    return {
        "imported": result.imported,
        "updated": result.updated,
        "skipped": result.skipped,
        "items": [issue.id for issue in items],
    }


@router.get("/pipelines")
async def evolution_pipelines(
    request: Request,
    limit: int | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """List active evolution pipeline runs.

    Args:
        request (Request): FastAPI request with app state.
        limit (int | None): Optional page size (default 50, max 200).
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: ``items`` list of pipeline summaries.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(evolution_pipelines)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    cap = 50 if limit is None else max(1, min(int(limit), 200))
    return {"items": list_active_pipelines(layout, limit=cap)}


@router.get("/pipelines/{issue_id}")
async def evolution_pipeline_detail(
    issue_id: str,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, Any]:
    """Return one pipeline detail with stage stepper and log tail.

    Args:
        issue_id (str): Issue id.
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, Any]: Pipeline detail payload.

    Raises:
        HTTPException: ``404`` when the issue is missing.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(evolution_pipeline_detail)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    detail = get_pipeline_detail(layout, issue_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="pipeline_not_found")
    return detail


@router.post("/pipelines/{issue_id}/kill")
async def evolution_pipeline_kill(
    issue_id: str,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, Any]:
    """Cancel an active evolution pipeline run.

    Args:
        issue_id (str): Issue id.
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        dict[str, Any]: Updated issue summary.

    Raises:
        HTTPException: ``404`` when the issue is missing.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(evolution_pipeline_kill)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    issue = kill_pipeline(layout, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="pipeline_not_found")
    await _publish_issue_event(
        request,
        {
            "issue_id": issue.id,
            "event": "transition",
            "state": issue.state,
            "pipeline_stage": issue.pipeline_stage,
            "line": "Pipeline killed.",
        },
    )
    return issue_to_api_dict(issue)


@router.post("/pipelines/{issue_id}/poll")
async def evolution_pipeline_poll(
    issue_id: str,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, Any]:
    """Manually refresh a Cursor Cloud issue by polling once (FL-4C.7).

    Only meaningful for issues with ``executor=cursor_cloud`` and a
    ``cursor_job_id``; silently returns the current issue state for other
    issue types (no-op, never 409).

    Args:
        issue_id (str): Issue id.
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        dict[str, Any]: Updated issue summary.

    Raises:
        HTTPException: ``404`` when the issue is missing.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(evolution_pipeline_poll)
        True
    """
    from sevn.evolution.router import (
        ExecutorBlockedError as _EBE,
    )
    from sevn.evolution.router import (
        poll_cursor_cloud_for_issue as _poll,
    )

    layout: WorkspaceLayout = request.app.state.layout
    ws: WorkspaceConfig = request.app.state.workspace
    conn: sqlite3.Connection = request.app.state.sqlite_conn

    issue = get_issue(layout, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="issue_not_found")

    if issue.executor == "cursor_cloud" and (issue.cursor_job_id or issue.cursor_agent_id):
        try:
            issue = await asyncio.to_thread(_poll, conn, layout, issue, ws=ws)
        except _EBE as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await _publish_issue_event(
            request,
            {
                "issue_id": issue.id,
                "event": "transition",
                "state": issue.state,
                "pipeline_stage": issue.pipeline_stage,
            },
        )

    return issue_to_api_dict(issue)


@router.post("/pipelines/{issue_id}/run")
async def evolution_pipeline_run(
    issue_id: str,
    body: RunPipelineBody,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, Any]:
    """Trigger or resume an evolution pipeline run from Mission Control.

    When ``live=True`` all three dry-run flags are set to ``False``; otherwise
    they fall back to ``my_sevn.pipelines.*_dry_run_default``.

    Args:
        issue_id (str): Issue id.
        body (RunPipelineBody): Run options (stage, executor, live flag).
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        dict[str, Any]: Updated issue summary after the dispatched step.

    Raises:
        HTTPException: ``404`` when the issue is missing.
        HTTPException: ``409`` when the issue is in ``awaiting_approval``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(evolution_pipeline_run)
        True
    """
    from sevn.evolution.pipeline_common import PipelineBlockedError as _PBE
    from sevn.evolution.pipeline_runner import run_pipeline as _run_pipeline

    ws: WorkspaceConfig = request.app.state.workspace
    layout: WorkspaceLayout = request.app.state.layout
    conn: sqlite3.Connection = request.app.state.sqlite_conn
    fanout = getattr(request.app.state, "evolution_issue_event_fanout", None)

    issue = get_issue(layout, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="issue_not_found")

    ci_dry: bool | None = False if body.live else None
    promo_dry: bool | None = False if body.live else None
    sk_dry: bool | None = False if body.live else None

    try:
        updated = await _run_pipeline(
            conn,
            ws,
            layout,
            issue_id,
            stage=body.stage,
            executor=body.executor,
            ci_dry_run=ci_dry,
            promotion_dry_run=promo_dry,
            spec_kit_dry_run=sk_dry,
            fanout=fanout,
        )
    except _PBE as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await _publish_issue_event(
        request,
        {
            "issue_id": updated.id,
            "event": "transition",
            "state": updated.state,
            "pipeline_stage": updated.pipeline_stage,
        },
    )
    return issue_to_api_dict(updated)


@router.get("/approvals")
async def evolution_approvals(
    request: Request,
    pending_only: bool = True,
    limit: int | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """List evolution HITL approvals (feature plan/tasks + optional improve plan).

    Args:
        request (Request): FastAPI request with app state.
        pending_only (bool): When true, return only pending rows (default).
        limit (int | None): Optional page size (default 50, max 200).
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: ``items`` approval list.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(evolution_approvals)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    cap = 50 if limit is None else max(1, min(int(limit), 200))
    for issue in list_issues(layout, limit=cap):
        if issue.state == "awaiting_approval":
            ensure_issue_approval(layout, issue)
    rows = list_approvals(layout, pending_only=pending_only, limit=cap)
    return {"items": [approval_to_api_dict(row) for row in rows]}


@router.post("/approvals/{approval_id}/approve")
async def evolution_approval_approve(
    approval_id: str,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, Any]:
    """Approve one pending evolution approval and unblock the pipeline.

    Args:
        approval_id (str): Approval id.
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        dict[str, Any]: Updated approval payload.

    Raises:
        HTTPException: ``404`` when the approval is missing.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(evolution_approval_approve)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    approval, issue = resolve_approval(layout, approval_id, "approve")
    if approval is None:
        raise HTTPException(status_code=404, detail="approval_not_found")
    if issue is not None:
        await _publish_issue_event(
            request,
            {
                "issue_id": issue.id,
                "event": "approval",
                "state": issue.state,
                "pipeline_stage": issue.pipeline_stage,
                "approval_id": approval.id,
            },
        )
        # Resume the pipeline without blocking the approval response (W0.1).
        if issue.pipeline_stage == "implementing":
            _enqueue_pipeline_resume(request, issue.id)
    return approval_to_api_dict(approval)


@router.post("/approvals/{approval_id}/reject")
async def evolution_approval_reject(
    approval_id: str,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, Any]:
    """Reject one pending evolution approval.

    Args:
        approval_id (str): Approval id.
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        dict[str, Any]: Updated approval payload.

    Raises:
        HTTPException: ``404`` when the approval is missing.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(evolution_approval_reject)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    approval, issue = resolve_approval(layout, approval_id, "reject")
    if approval is None:
        raise HTTPException(status_code=404, detail="approval_not_found")
    if issue is not None:
        await _publish_issue_event(
            request,
            {
                "issue_id": issue.id,
                "event": "approval",
                "state": issue.state,
                "pipeline_stage": issue.pipeline_stage,
                "approval_id": approval.id,
            },
        )
    return approval_to_api_dict(approval)


@router.post("/approvals/{approval_id}/edit")
async def evolution_approval_edit(
    approval_id: str,
    body: EditApprovalBody,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, Any]:
    """Edit plan body and approve one pending evolution approval.

    Args:
        approval_id (str): Approval id.
        body (EditApprovalBody): Replacement plan/tasks markdown.
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        dict[str, Any]: Updated approval payload.

    Raises:
        HTTPException: ``404`` when the approval is missing.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(evolution_approval_edit)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    approval, issue = resolve_approval(layout, approval_id, "edit", edit_body=body.body)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval_not_found")
    if issue is not None:
        await _publish_issue_event(
            request,
            {
                "issue_id": issue.id,
                "event": "approval",
                "state": issue.state,
                "pipeline_stage": issue.pipeline_stage,
                "approval_id": approval.id,
            },
        )
        # Resume the pipeline without blocking the edit response (W0.1).
        if issue.pipeline_stage == "implementing":
            _enqueue_pipeline_resume(request, issue.id)
    return approval_to_api_dict(approval)


@router.get("/traces")
async def evolution_traces(
    request: Request,
    limit: int | None = None,
    issue_id: str | None = None,
    job_id: str | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return evolution- and self-improve-scoped trace rows.

    Args:
        request (Request): FastAPI request with app state.
        limit (int | None): Optional page size.
        issue_id (str | None): Filter ``attrs.issue_id`` when set.
        job_id (str | None): Filter ``attrs.job_id`` when set.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Redacted trace page.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(evolution_traces)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    ws: WorkspaceConfig = request.app.state.workspace
    db_path = traces_sqlite_path(layout.content_root)
    conn = ensure_trace_connection(db_path)
    try:
        policy = trace_redaction_policy_for(ws)
        cap = clamp_limit(limit)
        page = list_trace_events(
            conn,
            limit=cap,
            policy=policy,
            kind_prefixes=_EVOLUTION_KIND_PREFIXES,
            issue_id=issue_id,
            job_id=job_id,
        )
        redacted = _redact_trace_page(page, policy)
        items = redacted.get("items")
        if isinstance(items, list):
            for row in items:
                if isinstance(row, dict):
                    attrs = row.get("attrs")
                    if isinstance(attrs, dict):
                        link_issue = attrs.get("issue_id")
                        link_job = attrs.get("job_id")
                        if link_issue:
                            row["issue_link"] = f"/mission/evolution/pipelines?issue={link_issue}"
                        if link_job:
                            row["job_link"] = f"/mission/jobs?job_id={link_job}"
        return redacted
    finally:
        conn.close()


@router.get("/stats")
async def evolution_stats(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, Any]:
    """Return evolution roll-up counters for Mission Control Stats tab.

    Args:
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, Any]: Stats payload.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(evolution_stats)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    conn: sqlite3.Connection = request.app.state.sqlite_conn
    return compute_evolution_stats(layout, conn)
