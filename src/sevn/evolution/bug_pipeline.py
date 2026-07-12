"""Bug evolution pipeline (`specs/35-bot-evolution.md` §4.2).

Module: sevn.evolution.bug_pipeline
Depends: sevn.config.my_sevn, sevn.evolution.executors.local, sevn.evolution.pipeline_common,
    sevn.evolution.router, sevn.evolution.spec_kit, sevn.evolution.worktree

Exports:
    run_bug_pipeline — triage → optional spec-kit → worktree → tier-B implement → test → promote.

Private:
    _bug_fix_prompt — load bug-fix agent playbook from the repo checkout.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sevn.config.my_sevn import (
    effective_my_sevn,
    effective_my_sevn_executors,
    effective_my_sevn_pipelines,
)
from sevn.evolution.approvals import create_approval, get_approval
from sevn.evolution.issues import EvolutionIssue, get_issue
from sevn.evolution.pipeline_common import PipelineBlockedError, publish_transition, set_issue_stage
from sevn.evolution.router import dispatch_cursor_cloud_implement, resolve_executor
from sevn.evolution.spec_kit import run_specify_allowlisted
from sevn.evolution.worktree import (
    WorktreeError,
    allocate_worktree,
    load_worktree_lease,
    promote_worktree,
    run_ci_smoke,
)

if TYPE_CHECKING:
    import sqlite3

    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.evolution.events import EvolutionIssueEventFanoutFn
    from sevn.workspace.layout import WorkspaceLayout

_BUG_FIX_PROMPT_REL = "evolution/agents/bug_fix.md"


def _bug_fix_prompt(repo_root: Path | None) -> str:
    """Load bug-fix agent playbook when the repo checkout is available.

    Args:
        repo_root (Path | None): sevn.bot checkout root.

    Returns:
        str: Playbook excerpt or fallback instruction.

    Examples:
        >>> len(_bug_fix_prompt(None)) > 0
        True
    """
    if repo_root is not None:
        path = repo_root / _BUG_FIX_PROMPT_REL
        if path.is_file():
            return path.read_text(encoding="utf-8")[:8000]
    return "Follow evolution/agents/bug_fix.md: triage, worktree-only edits, make ci, promote."


async def run_bug_pipeline(
    conn: sqlite3.Connection,
    ws: WorkspaceConfig,
    layout: WorkspaceLayout,
    issue_id: str,
    *,
    owner_principal: str = "owner",
    session_key: str = "",
    fanout: EvolutionIssueEventFanoutFn | None = None,
    ci_dry_run: bool | None = None,
    spec_kit_dry_run: bool | None = None,
    promotion_dry_run: bool | None = None,
    repo_root: Path | None = None,
) -> EvolutionIssue:
    """Run the bug pipeline for one issue through test and promotion.

    Stages: triage → optional ``speckit.plan`` → worktree → ``make ci`` → promote.
    When ``my_sevn.bugs.require_approval`` is true, blocks at ``awaiting_approval`` before
    implement. When executor is ``cursor_cloud``, delegates implement via
    :func:`dispatch_cursor_cloud_implement`.

    Dry-run flags default to ``my_sevn.pipelines.*_dry_run_default`` when ``None``; pass
    ``False`` explicitly (or set ``--live``) to run real CI + promotion.

    Args:
        conn (sqlite3.Connection): Workspace SQLite (Cursor Cloud jobs).
        ws (WorkspaceConfig): Parsed workspace config.
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.
        owner_principal (str): Owner principal for spec-kit audit.
        session_key (str): Gateway session key for cloud jobs.
        fanout (EvolutionIssueEventFanoutFn | None): Optional event publisher.
        ci_dry_run (bool | None): Skip real ``make ci``; defaults to
            ``my_sevn.pipelines.ci_dry_run_default``.
        spec_kit_dry_run (bool | None): Dry-run spec-kit stages; defaults to
            ``my_sevn.pipelines.spec_kit_dry_run_default``.
        promotion_dry_run (bool | None): Skip real ``promote_worktree``; defaults to
            ``my_sevn.pipelines.promotion_dry_run_default``.
        repo_root (Path | None): Optional explicit repo root for worktrees.

    Returns:
        EvolutionIssue: Updated issue row.

    Raises:
        PipelineBlockedError: When issue missing or approval required but pending.
        WorktreeError: When worktree allocation fails.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_bug_pipeline)
        True
    """
    issue = get_issue(layout, issue_id)
    if issue is None:
        msg = f"issue not found: {issue_id}"
        raise PipelineBlockedError(msg)
    if issue.kind != "bug":
        msg = f"issue {issue_id} is not a bug"
        raise PipelineBlockedError(msg)
    if issue.state in ("done", "cancelled"):
        return issue

    # Resolve dry-run flags from my_sevn.pipelines defaults when not explicitly passed.
    pipeline_cfg = effective_my_sevn_pipelines(ws)
    _ci_dry_run = pipeline_cfg.ci_dry_run_default if ci_dry_run is None else ci_dry_run
    _spec_kit_dry_run = (
        pipeline_cfg.spec_kit_dry_run_default if spec_kit_dry_run is None else spec_kit_dry_run
    )
    _promotion_dry_run = (
        pipeline_cfg.promotion_dry_run_default if promotion_dry_run is None else promotion_dry_run
    )

    my = effective_my_sevn(ws)
    bugs = my.bugs
    use_spec_kit = bool(bugs and bugs.use_spec_kit)
    require_approval = bool(bugs and bugs.require_approval)

    issue = set_issue_stage(
        layout,
        issue,
        state="open",
        pipeline_stage="open",
        log_line="Bug pipeline: triage started.",
    )
    await publish_transition(fanout, issue=issue, line="triage")
    # FL-4A.4: load the playbook now so it is available for the implement step.
    # dispatch_local_implement calls _bug_fix_prompt internally; we load it here
    # only to surface early failures (e.g. missing checkout) in the triage log.
    _playbook_preview = _bug_fix_prompt(repo_root)
    _ = _playbook_preview  # used by dispatch_local_implement via repo_root

    executor = resolve_executor(ws, "bug")
    issue.executor = executor  # type: ignore[assignment]  # resolve_executor → local|cursor_cloud

    if use_spec_kit:
        lease = load_worktree_lease(layout, issue.id)
        cwd = Path(lease.path) if lease else layout.content_root
        run_specify_allowlisted(
            "plan",
            [],
            cwd,
            owner_principal=owner_principal,
            ws=ws,
            layout=layout,
            issue_id=issue.id,
            dry_run=_spec_kit_dry_run,
        )
        issue = set_issue_stage(
            layout,
            issue,
            state="spec_kit",
            pipeline_stage="spec_kit",
            log_line="Optional spec-kit plan (dry-run) recorded.",
        )
        await publish_transition(fanout, issue=issue)

    if require_approval and issue.state != "implementing":
        if issue.approval_id:
            approval = get_approval(layout, issue.approval_id)
            if approval is None or approval.status != "approved":
                issue = set_issue_stage(
                    layout,
                    issue,
                    state="awaiting_approval",
                    pipeline_stage="awaiting_approval",
                    log_line="Waiting for owner approval before implement.",
                )
                await publish_transition(fanout, issue=issue)
                msg = f"bug {issue_id} blocked: approval pending"
                raise PipelineBlockedError(msg)
        else:
            approval = create_approval(
                layout,
                kind="feature_tasks",
                title=f"Bug fix approval: {issue.title}",
                body=issue.body or "(no body)",
                issue_id=issue.id,
            )
            issue.approval_id = approval.id
            issue = set_issue_stage(
                layout,
                issue,
                state="awaiting_approval",
                pipeline_stage="awaiting_approval",
                log_line="Bug fix requires owner approval.",
            )
            await publish_transition(fanout, issue=issue)
            msg = f"bug {issue_id} blocked: approval required"
            raise PipelineBlockedError(msg)

    if executor == "cursor_cloud":
        _poll_mode = effective_my_sevn_executors(ws).cursor_poll_mode
        issue = dispatch_cursor_cloud_implement(
            conn,
            ws,
            layout,
            issue.id,
            session_key=session_key,
            poll=(_poll_mode == "inline"),
        )
        await publish_transition(fanout, issue=issue, line="Delegated to Cursor Cloud.")
        return issue

    if load_worktree_lease(layout, issue.id) is None:
        allocate_worktree(
            layout,
            issue.id,
            repo_root=repo_root,
            executor="local",
            owner_principal=owner_principal,
        )

    issue = set_issue_stage(
        layout,
        issue,
        state="implementing",
        pipeline_stage="implementing",
        log_line="Implementing in local worktree.",
    )
    await publish_transition(fanout, issue=issue)

    # FL-4A.3: tier-B implement step (between allocate_worktree and run_ci_smoke).
    # Lazy import breaks the bug_pipeline <-> executors.local cycle (local.py imports
    # ``_bug_fix_prompt`` from this module at top level).
    from sevn.evolution.executors.local import dispatch_local_implement

    issue = await dispatch_local_implement(
        conn,
        ws,
        layout,
        issue,
        session_key=session_key,
        repo_root=repo_root,
        fanout=fanout,
    )

    lease = load_worktree_lease(layout, issue.id)
    if lease is None:
        msg = f"worktree missing after allocate for {issue_id}"
        raise WorktreeError(msg)
    smoke = run_ci_smoke(Path(lease.path), dry_run=_ci_dry_run)
    if not smoke.ok:
        append_line = f"make ci failed: {smoke.stderr or smoke.stdout}"
        issue = set_issue_stage(layout, issue, state="implementing", log_line=append_line)
        msg = append_line
        raise WorktreeError(msg)

    issue = set_issue_stage(
        layout,
        issue,
        state="implementing",
        log_line="make ci smoke passed.",
    )
    promote_worktree(layout, issue.id, ws, dry_run=_promotion_dry_run)
    issue = set_issue_stage(
        layout,
        issue,
        state="done",
        pipeline_stage="done",
        log_line="Bug pipeline complete.",
    )
    await publish_transition(fanout, issue=issue)
    return issue


__all__ = ["run_bug_pipeline"]
