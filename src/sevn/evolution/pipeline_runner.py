"""Evolution pipeline résumé façade (`specs/35-bot-evolution.md` FL-2).

``run_pipeline`` is the single entry-point for resuming *any* evolution issue from
any stage.  Callers pass the issue id and an optional ``stage`` hint; the façade
reads the live ``pipeline_stage``/``state`` off the issue and decides what to do:

- ``open`` / ``spec_kit``   → kick off the appropriate pipeline from the top.
- ``awaiting_approval``     → raise :class:`.PipelineBlockedError` (HITL required).
- ``implementing`` + cloud  → poll only (idempotent).
- ``implementing`` + local  → implement-or-CI → promote.

The function is *async* and fire-and-forget safe: callers (dashboard endpoints,
Telegram gate) schedule it with ``spawn_logged(run_pipeline(...))`` so the
approval response returns immediately without blocking the poll loop (W0.1).

Module: sevn.evolution.pipeline_runner
Depends: sevn.config.my_sevn, sevn.evolution.bug_pipeline,
    sevn.evolution.feature_pipeline, sevn.evolution.issues,
    sevn.evolution.pipeline_common, sevn.evolution.promotion,
    sevn.evolution.router, sevn.evolution.worktree

Exports:
    run_pipeline — résumé façade: load issue, resolve stage, dispatch.

Private:
    _resolve_dry_runs — coerce None flags to my_sevn.pipelines defaults.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from loguru import logger

from sevn.config.my_sevn import effective_my_sevn_pipelines
from sevn.evolution.bug_pipeline import run_bug_pipeline
from sevn.evolution.feature_pipeline import run_feature_pipeline
from sevn.evolution.issues import EvolutionIssue, get_issue
from sevn.evolution.pipeline_common import PipelineBlockedError, set_issue_stage
from sevn.evolution.router import poll_cursor_cloud_for_issue, resolve_executor
from sevn.evolution.worktree import load_worktree_lease, run_ci_smoke

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from sevn.config.workspace_config import EvolutionExecutorKind, WorkspaceConfig
    from sevn.evolution.events import EvolutionIssueEventFanoutFn
    from sevn.integrations.github_skill.hooks import GithubSkillHooks
    from sevn.workspace.layout import WorkspaceLayout

_StageHint = Literal["auto", "plan", "implement", "ci", "promote"]


def _resolve_dry_runs(
    ws: WorkspaceConfig,
    *,
    ci_dry_run: bool | None,
    spec_kit_dry_run: bool | None,
    promotion_dry_run: bool | None,
) -> tuple[bool, bool, bool]:
    """Coerce ``None`` dry-run flags to ``my_sevn.pipelines`` defaults.

    Args:
        ws (WorkspaceConfig): Workspace config.
        ci_dry_run (bool | None): Explicit CI flag or ``None``.
        spec_kit_dry_run (bool | None): Explicit spec-kit flag or ``None``.
        promotion_dry_run (bool | None): Explicit promotion flag or ``None``.

    Returns:
        tuple[bool, bool, bool]: Resolved ``(ci_dry_run, spec_kit_dry_run, promotion_dry_run)``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _resolve_dry_runs(
        ...     WorkspaceConfig.minimal(),
        ...     ci_dry_run=None,
        ...     spec_kit_dry_run=None,
        ...     promotion_dry_run=None,
        ... )
        (True, False, True)
    """
    cfg = effective_my_sevn_pipelines(ws)
    return (
        cfg.ci_dry_run_default if ci_dry_run is None else ci_dry_run,
        cfg.spec_kit_dry_run_default if spec_kit_dry_run is None else spec_kit_dry_run,
        cfg.promotion_dry_run_default if promotion_dry_run is None else promotion_dry_run,
    )


async def run_pipeline(
    conn: sqlite3.Connection,
    ws: WorkspaceConfig,
    layout: WorkspaceLayout,
    issue_id: str,
    *,
    stage: _StageHint = "auto",
    executor: EvolutionExecutorKind | None = None,
    ci_dry_run: bool | None = None,
    promotion_dry_run: bool | None = None,
    spec_kit_dry_run: bool | None = None,
    session_key: str = "",
    fanout: EvolutionIssueEventFanoutFn | None = None,
    repo_root: Path | None = None,
    hooks: GithubSkillHooks | None = None,
    repo: str = "",
) -> EvolutionIssue:
    """Resume or start the evolution pipeline for one issue.

    Reads the live ``pipeline_stage`` and ``state`` off the issue and dispatches
    to the appropriate pipeline, poll, or CI step.  This function is the sole
    resume entry-point; callers should *not* call ``run_bug_pipeline`` /
    ``run_feature_pipeline`` directly after an approval — they should call this.

    Blocking rules:
    - ``awaiting_approval`` always raises :class:`PipelineBlockedError` — the
      issue cannot be resumed without HITL; callers should not retry.
    - ``done`` / ``cancelled`` returns the issue unchanged (idempotent).

    Args:
        conn (sqlite3.Connection): Workspace SQLite (Cursor Cloud jobs).
        ws (WorkspaceConfig): Parsed workspace config.
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.
        stage (_StageHint): Hint for which stage to resume from.  ``"auto"``
            reads live state; explicit hints skip earlier stages.
        executor (EvolutionExecutorKind | None): Runtime executor override.
            ``None`` resolves from ``my_sevn.executors`` via ``resolve_executor``.
            ``"chat"`` is a runtime-only value (C3) — not persisted to config.
        ci_dry_run (bool | None): Skip real ``make ci``; defaults to
            ``my_sevn.pipelines.ci_dry_run_default``.
        promotion_dry_run (bool | None): Skip real ``promote_worktree``; defaults
            to ``my_sevn.pipelines.promotion_dry_run_default``.
        spec_kit_dry_run (bool | None): Dry-run spec-kit stages; defaults to
            ``my_sevn.pipelines.spec_kit_dry_run_default``.
        session_key (str): Gateway session key for cloud jobs.
        fanout (EvolutionIssueEventFanoutFn | None): Optional event publisher.
        repo_root (Path | None): Optional explicit repo root for worktrees.
        hooks (GithubSkillHooks | None): GitHub skill hooks for PR creation.
            When provided (with ``repo``), the promote step opens a real PR via
            :func:`~sevn.evolution.promotion.promote_issue`.  When ``None``,
            falls back to the legacy push-only :func:`~sevn.evolution.worktree.promote_worktree`.
        repo (str): ``owner/repo`` slug for PR creation (used with ``hooks``).

    Returns:
        EvolutionIssue: Updated issue row after the dispatched step completes.

    Raises:
        PipelineBlockedError: When the issue is in ``awaiting_approval`` (requires
            HITL), or when the issue is not found.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_pipeline)
        True
    """
    issue = get_issue(layout, issue_id)
    if issue is None:
        msg = f"run_pipeline: issue not found: {issue_id}"
        raise PipelineBlockedError(msg)

    live_stage = issue.pipeline_stage or issue.state or "open"
    effective_stage = live_stage if stage == "auto" else stage

    # Terminal states — nothing to do.
    if issue.state in ("done", "cancelled"):
        logger.debug(f"run_pipeline: issue {issue_id} is {issue.state} — no-op")
        return issue

    # HITL gate — never auto-advance past this; callers must wait for approval.
    if live_stage == "awaiting_approval" and stage == "auto":
        msg = f"run_pipeline: issue {issue_id} is awaiting_approval — HITL required"
        raise PipelineBlockedError(msg)

    ci_run, sk_run, promo_run = _resolve_dry_runs(
        ws,
        ci_dry_run=ci_dry_run,
        spec_kit_dry_run=spec_kit_dry_run,
        promotion_dry_run=promotion_dry_run,
    )

    logger.info(
        f"run_pipeline: issue={issue_id} kind={issue.kind} "
        f"live_stage={live_stage} effective_stage={effective_stage} "
        f"ci_dry={ci_run} sk_dry={sk_run} promo_dry={promo_run}"
    )

    # Normalise stage alias: "implement" == "implementing" for routing logic.
    is_implement_stage = effective_stage in ("implement", "implementing")

    # --- implementing + cursor_cloud → poll only ---
    if is_implement_stage and issue.cursor_agent_id:
        logger.info(f"run_pipeline: polling cursor cloud for {issue_id}")
        return poll_cursor_cloud_for_issue(conn, layout, issue)

    # --- implementing + local lease (or no lease) → dispatch tier-B implement then CI ---
    # FL-4A.3: if no cursor agent and the issue is implementing, run dispatch_local_implement
    # first (which requires an existing worktree lease), then fall through to CI + promote.
    # When there is no lease yet we allocate one before dispatching.
    if is_implement_stage and not issue.cursor_agent_id:
        from pathlib import Path as _Path

        from sevn.evolution.executors.local import dispatch_local_implement
        from sevn.evolution.worktree import allocate_worktree

        lease = load_worktree_lease(layout, issue_id)
        if lease is None:
            allocate_worktree(
                layout,
                issue_id,
                repo_root=repo_root,
                executor="local",
            )
            lease = load_worktree_lease(layout, issue_id)
        if lease is not None:
            issue = await dispatch_local_implement(
                conn,
                ws,
                layout,
                issue,
                session_key=session_key,
                repo_root=repo_root,
                fanout=fanout,
            )
        else:
            logger.warning(
                "run_pipeline: {issue_id} is implementing but worktree allocation failed — "
                "cannot dispatch local implement",
                issue_id=issue_id,
            )
            return issue

    # --- implementing + local lease → run CI then promote ---
    if is_implement_stage and issue.kind == "bug":
        lease = load_worktree_lease(layout, issue_id)
        if lease is not None:
            from pathlib import Path as _Path

            smoke = run_ci_smoke(_Path(lease.path), dry_run=ci_run)
            if not smoke.ok:
                from sevn.evolution.issues import save_issue, utc_now_iso
                from sevn.evolution.pipelines import append_pipeline_log

                line = f"make ci failed: {smoke.stderr or smoke.stdout}"
                append_pipeline_log(layout, issue_id=issue_id, line=line)
                issue.updated_at = utc_now_iso()
                return save_issue(layout, issue)

            # Promote: use promote_issue (async, full PR) when hooks+repo are
            # available; fall back to the legacy sync promote_worktree otherwise.
            if hooks is not None and repo:
                from sevn.evolution.promotion import promote_issue

                return await promote_issue(
                    layout,
                    issue,
                    hooks=hooks,
                    repo=repo,
                    promotion_dry_run=promo_run,
                )
            from sevn.evolution.worktree import promote_worktree

            promote_worktree(layout, issue_id, ws, dry_run=promo_run)
            return set_issue_stage(
                layout,
                issue,
                state="done",
                pipeline_stage="done",
                log_line="Pipeline runner: CI passed, promoted.",
            )

    # --- open / spec_kit / explicit plan or implement → dispatch full pipeline ---
    eff_executor: EvolutionExecutorKind = executor or resolve_executor(ws, issue.kind)

    if eff_executor == "chat":
        # FL-4B: chat track — the gateway bridge (evolution_chat_bridge.py) drives the
        # PlanGate plan step (requires gateway-coupled objects: _run_cd_dispatch, plan_registry).
        # By the time run_pipeline is called with executor="chat" at stage "implement", the
        # plan is already approved and we fall through to dispatch_local_implement.
        # For earlier stages (open/spec_kit), fall through to the local pipeline which will
        # allocate the worktree and run dispatch_local_implement once implementing.
        logger.info(f"run_pipeline: chat executor for {issue_id} — routing to local implement")
        eff_executor = "local"

    if issue.kind == "bug":
        return await run_bug_pipeline(
            conn,
            ws,
            layout,
            issue_id,
            session_key=session_key,
            fanout=fanout,
            ci_dry_run=ci_run,
            spec_kit_dry_run=sk_run,
            promotion_dry_run=promo_run,
            repo_root=repo_root,
        )

    # feature
    return await run_feature_pipeline(
        conn,
        ws,
        layout,
        issue_id,
        session_key=session_key,
        fanout=fanout,
        ci_dry_run=ci_run,
        spec_kit_dry_run=sk_run,
        promotion_dry_run=promo_run,
        repo_root=repo_root,
    )


__all__ = ["run_pipeline"]
