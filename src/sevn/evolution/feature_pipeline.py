"""Feature evolution pipeline (`specs/35-bot-evolution.md` §4.1).

Module: sevn.evolution.feature_pipeline
Depends: sevn.evolution.approvals, sevn.evolution.pipeline_common, sevn.evolution.router,
    sevn.evolution.spec_kit, sevn.evolution.worktree

Exports:
    FeaturePipelineBlockedError — implement blocked without HITL approval.
    feature_artefacts_dir — resolve ``evolution/features/<issue-id>/``.
    record_pipeline_approval — link an approved approval and resume when allowed.
    run_feature_pipeline — specify → plan → approval gate → tasks → implement.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sevn.config.my_sevn import effective_my_sevn, effective_my_sevn_pipelines
from sevn.evolution.approvals import create_approval, ensure_issue_approval, get_approval
from sevn.evolution.issues import EvolutionIssue, get_issue
from sevn.evolution.pipeline_common import PipelineBlockedError, publish_transition, set_issue_stage
from sevn.evolution.router import dispatch_cursor_cloud_implement, resolve_executor
from sevn.evolution.spec_kit import (
    _effective_spec_kit,
    _try_resolve_repo_root,
    run_specify_allowlisted,
)
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

_FEATURE_SPEC_PROMPT = "evolution/agents/feature_spec.md"


class FeaturePipelineBlockedError(PipelineBlockedError):
    """Feature path blocked before owner approval (HITL)."""


def feature_artefacts_dir(
    ws: WorkspaceConfig,
    layout: WorkspaceLayout,
    issue_id: str,
) -> Path:
    """Return feature spec-kit artefact directory for one issue.

    Prefers repo ``evolution/features/<id>/`` when checkout exists; else workspace mirror.

    Args:
        ws (WorkspaceConfig): Parsed workspace.
        layout (WorkspaceLayout): Workspace layout for mirror path.
        issue_id (str): Issue id.

    Returns:
        Path: Artefact directory (created when missing).

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> ws = WorkspaceConfig.minimal()
        >>> ly = WorkspaceLayout(Path("/tmp/s.json"), Path("/tmp/w"))
        >>> feature_artefacts_dir(ws, ly, "abc").name
        'abc'
    """
    rel = _effective_spec_kit(ws).features_dir.replace("\\", "/").strip("/")
    repo = _try_resolve_repo_root()
    if repo is not None:
        target = repo / rel / issue_id
        target.mkdir(parents=True, exist_ok=True)
        return target
    mirror = layout.content_root / rel / issue_id
    mirror.mkdir(parents=True, exist_ok=True)
    return mirror


def _feature_spec_prompt(repo_root: Path | None) -> str:
    """Load feature spec-kit playbook text.

    Args:
        repo_root (Path | None): sevn.bot checkout.

    Returns:
        str: Playbook body or fallback.

    Examples:
        >>> len(_feature_spec_prompt(None)) > 0
        True
    """
    if repo_root is not None:
        path = repo_root / _FEATURE_SPEC_PROMPT
        if path.is_file():
            return path.read_text(encoding="utf-8")[:8000]
    return "Follow evolution/agents/feature_spec.md for required spec-kit + HITL."


def _seed_constitution_snapshot(
    artefacts: Path, ws: WorkspaceConfig, layout: WorkspaceLayout
) -> None:
    """Copy constitution excerpt into feature artefacts when missing.

    Args:
        artefacts (Path): Feature artefact directory.
        ws (WorkspaceConfig): Workspace config.
        layout (WorkspaceLayout): Workspace layout.

    Returns:
        None: Always.

    Examples:
        >>> _seed_constitution_snapshot.__name__
        '_seed_constitution_snapshot'
    """
    from sevn.evolution.spec_kit import load_constitution

    dest = artefacts / "constitution.md"
    if dest.is_file():
        return
    payload = load_constitution(ws, layout)
    dest.write_text(payload.text, encoding="utf-8")


def _approval_is_satisfied(layout: WorkspaceLayout, issue: EvolutionIssue) -> bool:
    """Return whether feature implement may proceed.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue (EvolutionIssue): Issue row.

    Returns:
        bool: True when approval not required or approval is approved.

    Examples:
        >>> _approval_is_satisfied.__name__
        '_approval_is_satisfied'
    """
    if not issue.approval_id:
        return False
    approval = get_approval(layout, issue.approval_id)
    return approval is not None and approval.status == "approved"


async def record_pipeline_approval(
    layout: WorkspaceLayout,
    issue_id: str,
    approval_id: str,
    *,
    fanout: EvolutionIssueEventFanoutFn | None = None,
) -> EvolutionIssue:
    """Record that an approval id is linked and approved; unblock feature pipeline stage.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.
        approval_id (str): Approved approval id.
        fanout (EvolutionIssueEventFanoutFn | None): Optional event publisher.

    Returns:
        EvolutionIssue: Updated issue ready for ``tasks`` / ``implement``.

    Raises:
        FeaturePipelineBlockedError: When approval missing or not approved.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(record_pipeline_approval)
        True
    """
    issue = get_issue(layout, issue_id)
    if issue is None:
        msg = f"issue not found: {issue_id}"
        raise FeaturePipelineBlockedError(msg)
    approval = get_approval(layout, approval_id)
    if approval is None:
        msg = f"approval not found: {approval_id}"
        raise FeaturePipelineBlockedError(msg)
    if approval.status != "approved":
        msg = f"approval {approval_id} is not approved"
        raise FeaturePipelineBlockedError(msg)
    issue.approval_id = approval_id
    issue = set_issue_stage(
        layout,
        issue,
        state="implementing",
        pipeline_stage="implementing",
        log_line=f"Approval {approval_id} recorded — pipeline unblocked.",
    )
    await publish_transition(fanout, issue=issue)
    return issue


async def run_feature_pipeline(
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
    skip_implement: bool = False,
) -> EvolutionIssue:
    """Run the feature pipeline through spec-kit stages and optional implement.

    Required path: ``specify`` → ``plan`` → **block until approval** → ``tasks`` →
    ``implement`` (local worktree or Cursor Cloud). Artefacts live under
    ``evolution/features/<issue-id>/``.

    Dry-run flags default to ``my_sevn.pipelines.*_dry_run_default`` when ``None``; pass
    ``False`` explicitly (or set ``--live``) to run real CI + promotion.

    Args:
        conn (sqlite3.Connection): Workspace SQLite.
        ws (WorkspaceConfig): Parsed workspace.
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.
        owner_principal (str): Owner principal for spec-kit audit.
        session_key (str): Gateway session key for cloud delegation.
        fanout (EvolutionIssueEventFanoutFn | None): Optional event publisher.
        ci_dry_run (bool | None): Skip real ``make ci``; defaults to
            ``my_sevn.pipelines.ci_dry_run_default``.
        spec_kit_dry_run (bool | None): Dry-run spec-kit stages; defaults to
            ``my_sevn.pipelines.spec_kit_dry_run_default``.
        promotion_dry_run (bool | None): Skip real ``promote_worktree``; defaults to
            ``my_sevn.pipelines.promotion_dry_run_default``.
        repo_root (Path | None): Optional repo root for worktrees.
        skip_implement (bool): Stop after approval gate (tests).

    Returns:
        EvolutionIssue: Updated issue (may be ``awaiting_approval``).

    Raises:
        FeaturePipelineBlockedError: When HITL approval is required but missing.
        WorktreeError: When worktree or CI fails.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_feature_pipeline)
        True
    """
    issue = get_issue(layout, issue_id)
    if issue is None:
        msg = f"issue not found: {issue_id}"
        raise FeaturePipelineBlockedError(msg)
    if issue.kind != "feature":
        msg = f"issue {issue_id} is not a feature"
        raise FeaturePipelineBlockedError(msg)
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
    features = my.features
    require_approval = True if features is None else features.require_approval
    # FL-4A.4 (feature path): load playbook for early failure detection;
    # dispatch_local_implement calls _feature_spec_prompt internally via repo_root.
    _playbook_preview = _feature_spec_prompt(repo_root)
    _ = _playbook_preview  # used by dispatch_local_implement via repo_root

    artefacts = feature_artefacts_dir(ws, layout, issue.id)
    artefacts.mkdir(parents=True, exist_ok=True)
    _seed_constitution_snapshot(artefacts, ws, layout)

    run_specify_allowlisted(
        "specify",
        [],
        artefacts,
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
        log_line="speckit.specify complete.",
    )
    await publish_transition(fanout, issue=issue)

    run_specify_allowlisted(
        "plan",
        [],
        artefacts,
        owner_principal=owner_principal,
        ws=ws,
        layout=layout,
        issue_id=issue.id,
        dry_run=_spec_kit_dry_run,
    )
    plan_path = artefacts / "plan.md"
    if not plan_path.is_file():
        plan_path.write_text(f"# Plan for {issue.title}\n\n{issue.body}\n", encoding="utf-8")

    if require_approval and not _approval_is_satisfied(layout, issue):
        approval = ensure_issue_approval(layout, issue) or create_approval(
            layout,
            kind="feature_plan",
            title=f"Feature plan: {issue.title}",
            body=plan_path.read_text(encoding="utf-8"),
            issue_id=issue.id,
        )
        issue.approval_id = approval.id
        issue = set_issue_stage(
            layout,
            issue,
            state="awaiting_approval",
            pipeline_stage="awaiting_approval",
            log_line="Blocked until owner approval (HITL).",
        )
        await publish_transition(fanout, issue=issue, line="awaiting_approval")
        msg = f"feature {issue_id} blocked: approval required"
        raise FeaturePipelineBlockedError(msg)

    if skip_implement:
        return issue

    run_specify_allowlisted(
        "tasks",
        [],
        artefacts,
        owner_principal=owner_principal,
        ws=ws,
        layout=layout,
        issue_id=issue.id,
        dry_run=_spec_kit_dry_run,
    )
    tasks_path = artefacts / "tasks.md"
    if not tasks_path.is_file():
        tasks_path.write_text(f"# Tasks for {issue.title}\n", encoding="utf-8")

    executor = resolve_executor(ws, "feature")
    issue.executor = executor  # type: ignore[assignment]  # resolve_executor → local|cursor_cloud

    if executor == "cursor_cloud":
        from sevn.config.my_sevn import effective_my_sevn_executors as _eff_exec

        _poll_mode = _eff_exec(ws).cursor_poll_mode
        issue = dispatch_cursor_cloud_implement(
            conn,
            ws,
            layout,
            issue.id,
            session_key=session_key,
            poll=(_poll_mode == "inline"),
        )
        await publish_transition(fanout, issue=issue, line="Feature delegated to Cursor Cloud.")
        return issue

    if load_worktree_lease(layout, issue.id) is None:
        allocate_worktree(
            layout,
            issue.id,
            repo_root=repo_root,
            executor="local",
            owner_principal=owner_principal,
        )

    lease = load_worktree_lease(layout, issue.id)
    implement_cwd = Path(lease.path) if lease is not None else artefacts
    run_specify_allowlisted(
        "implement",
        [],
        implement_cwd,
        owner_principal=owner_principal,
        ws=ws,
        layout=layout,
        issue_id=issue.id,
        dry_run=_spec_kit_dry_run,
    )

    issue = set_issue_stage(
        layout,
        issue,
        state="implementing",
        pipeline_stage="implementing",
        log_line="speckit.implement in worktree.",
    )
    await publish_transition(fanout, issue=issue)

    # FL-4A.3: tier-B implement step (between allocate_worktree and run_ci_smoke).
    # Lazy import breaks the feature_pipeline <-> executors.local cycle (local.py imports
    # ``_feature_spec_prompt`` from this module at top level).
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
        msg = f"worktree missing for feature {issue_id}"
        raise WorktreeError(msg)
    smoke = run_ci_smoke(Path(lease.path), dry_run=_ci_dry_run)
    if not smoke.ok:
        msg = smoke.stderr or smoke.stdout or "make ci failed"
        raise WorktreeError(msg)

    promote_worktree(layout, issue.id, ws, dry_run=_promotion_dry_run)
    issue = set_issue_stage(
        layout,
        issue,
        state="done",
        pipeline_stage="done",
        log_line="Feature pipeline complete.",
    )
    await publish_transition(fanout, issue=issue)
    return issue


__all__ = [
    "FeaturePipelineBlockedError",
    "feature_artefacts_dir",
    "record_pipeline_approval",
    "run_feature_pipeline",
]
