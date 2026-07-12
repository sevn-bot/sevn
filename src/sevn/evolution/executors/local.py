"""Local tier-B worktree executor (`specs/35-bot-evolution.md` FL-4A).

Assembles the ``run_b_turn`` input bundle from evolution primitives, avoiding a
full gateway boot.  All gateway-coupled objects (``ToolSet``, ``ToolExecutor``,
``TriageResult``, ``ToolContext``, ``ResolvedTierBModel``) are constructed here
with evolution-specific settings so the executor is self-contained.

Module: sevn.evolution.executors.local
Depends: sevn.agent.executors.b_harness, sevn.agent.triager.models,
    sevn.agent.executors.b_types, sevn.config.model_resolution,
    sevn.config.my_sevn, sevn.config.settings,
    sevn.evolution.bug_pipeline, sevn.evolution.feature_pipeline,
    sevn.evolution.issues, sevn.evolution.pipeline_common,
    sevn.tools.registry, sevn.tools.context, sevn.tools.permissions

Exports:
    dispatch_local_implement — tier-B implement in a worktree; returns updated issue.

Private:
    _build_implement_prompt — assemble the implement prompt text.
    _spec_kit_artefact_paths — return {spec,plan,tasks} paths for a feature issue.
    _pinned_tool_names — canonical tool allowlist for evolution tier-B.
    _build_b_turn_inputs — assemble TriageResult, ToolSet, ToolExecutor, ToolContext,
        ResolvedTierBModel without a live gateway session.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from sevn.agent.executors.b_harness import run_b_turn
from sevn.agent.executors.b_types import ResolvedTierBModel, SessionHandle
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.resolve import resolve_model
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.config.model_resolution import (
    ModelSlot,
    resolve_model_slot,
    resolve_transport_for_model_id,
)
from sevn.config.my_sevn import effective_my_sevn_pipelines
from sevn.config.settings import ProcessSettings
from sevn.evolution.bug_pipeline import _bug_fix_prompt
from sevn.evolution.feature_pipeline import _feature_spec_prompt, feature_artefacts_dir
from sevn.evolution.pipeline_common import publish_transition, set_issue_stage
from sevn.evolution.worktree import WorktreeError, load_worktree_lease
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry

if TYPE_CHECKING:
    import sqlite3

    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.evolution.events import EvolutionIssueEventFanoutFn
    from sevn.evolution.issues import EvolutionIssue
    from sevn.tools.base import ToolExecutor
    from sevn.tools.registry import ToolSet
    from sevn.workspace.layout import WorkspaceLayout

# ---------------------------------------------------------------------------
# Pinned tool allowlist (L5 — no re-triage can drop these).
# ---------------------------------------------------------------------------

#: Tool names always available to the evolution tier-B executor.
#: read/edit/write/glob/grep   — file editing
#: sandbox_exec / terminal_run — ``make ci`` + ``gh pr create``
#: run_skill_script            — skill scripts (gh, graphify, …)
#: integration_call            — structured API calls (e.g. GitHub REST)
_EVOLUTION_PINNED_TOOLS: tuple[str, ...] = (
    "read",
    "edit",
    "write",
    "glob",
    "grep",
    "sandbox_exec",
    "terminal_run",
    "run_skill_script",
    "integration_call",
)

#: Evolution skills surfaced to the executor.
_EVOLUTION_SKILLS: tuple[str, ...] = ("evolution",)

# Hard size cap for playbook text embedded in the prompt.
_PLAYBOOK_MAX_CHARS = 8_000


def _pinned_tool_names() -> list[str]:
    """Return the canonical pinned tool allowlist for evolution tier-B (L5).

    Returns:
        list[str]: Ordered tool names.

    Examples:
        >>> names = _pinned_tool_names()
        >>> "read" in names and "integration_call" in names
        True
    """
    return list(_EVOLUTION_PINNED_TOOLS)


def _spec_kit_artefact_paths(
    ws: WorkspaceConfig,
    layout: WorkspaceLayout,
    issue: EvolutionIssue,
) -> dict[str, Path | None]:
    """Return the spec/plan/tasks artefact paths for a feature issue.

    Falls back to ``None`` for each path that does not exist yet.

    Args:
        ws (WorkspaceConfig): Workspace config.
        layout (WorkspaceLayout): Workspace layout.
        issue (EvolutionIssue): Feature issue.

    Returns:
        dict[str, Path | None]: Keys ``spec``, ``plan``, ``tasks``; value is the
        resolved path when the file exists, else ``None``.

    Examples:
        >>> _spec_kit_artefact_paths.__name__
        '_spec_kit_artefact_paths'
    """
    artefacts = feature_artefacts_dir(ws, layout, issue.id)
    result: dict[str, Path | None] = {}
    for name in ("spec", "plan", "tasks"):
        p = artefacts / f"{name}.md"
        result[name] = p if p.is_file() else None
    return result


def _build_implement_prompt(
    ws: WorkspaceConfig,
    layout: WorkspaceLayout,
    issue: EvolutionIssue,
    *,
    worktree_path: Path,
    repo_root: Path | None,
) -> str:
    """Build the full implement prompt for the tier-B executor.

    Prompt sections (in order):
    1. Bug-fix or feature-spec playbook (from repo checkout or fallback).
    2. Issue title + body.
    3. Feature-only: paths to ``spec.md``, ``plan.md``, ``tasks.md`` (when present).
    4. Hard constraint: edit only under the worktree path.

    Args:
        ws (WorkspaceConfig): Workspace config.
        layout (WorkspaceLayout): Workspace layout.
        issue (EvolutionIssue): Issue being implemented.
        worktree_path (Path): Resolved worktree checkout path.
        repo_root (Path | None): Sevn.bot checkout root.

    Returns:
        str: Full implement prompt text.

    Examples:
        >>> _build_implement_prompt.__name__
        '_build_implement_prompt'
    """
    parts: list[str] = []

    # 1. Playbook
    if issue.kind == "bug":
        playbook = _bug_fix_prompt(repo_root)
    else:
        playbook = _feature_spec_prompt(repo_root)
    parts.append(playbook[:_PLAYBOOK_MAX_CHARS])

    # 2. Issue summary
    parts.append(
        f"## Issue to implement\n\n"
        f"**Title:** {issue.title}\n\n"
        f"**Body:**\n{issue.body or '(no body)'}"
    )

    # 3. Feature artefact paths
    if issue.kind == "feature":
        artefact_paths = _spec_kit_artefact_paths(ws, layout, issue)
        path_lines: list[str] = []
        for key in ("spec", "plan", "tasks"):
            p = artefact_paths[key]
            if p is not None:
                path_lines.append(f"- **{key}.md:** `{p}`")
        if path_lines:
            parts.append(
                "## Spec-kit artefacts (read these before editing)\n\n" + "\n".join(path_lines)
            )

    # 4. Hard constraint
    parts.append(
        f"## Constraint\n\n"
        f"You **must** edit files only under `{worktree_path}`. "
        "Do not modify files outside this worktree. "
        "When done, confirm the changes and run `make ci` inside the worktree."
    )

    return "\n\n---\n\n".join(parts)


def _build_transport_bundle(
    ws: WorkspaceConfig,
    process: ProcessSettings,
) -> ResolvedTierBModel:
    """Resolve tier-B model + transport from workspace config.

    Mirrors the logic of ``gateway.agent_turn._resolve_tier_b_bundle`` but does
    not require the full gateway import tree — reuses the public model-resolution
    helpers directly.

    Args:
        ws (WorkspaceConfig): Parsed workspace.
        process (ProcessSettings): Process settings (proxy URL).

    Returns:
        ResolvedTierBModel: Bundle passed to ``run_b_turn``.

    Examples:
        >>> _build_transport_bundle.__name__
        '_build_transport_bundle'
    """
    model_id = resolve_model_slot(ws, ModelSlot.tier_b)
    providers: dict[str, object] = {}
    raw = ws.providers
    if raw is not None:
        providers = (
            raw
            if isinstance(raw, dict)
            else (raw.model_dump() if hasattr(raw, "model_dump") else {})
        )
    transport_name = resolve_transport_for_model_id(providers, model_id)
    _, transport = resolve_model(
        model_id=model_id,
        transport_name=transport_name,
        proxy_base_url=process.proxy_url,
    )
    return ResolvedTierBModel(
        model_id=model_id,
        transport=transport,
        budget=ModelBudget(model_id=model_id, regime=BudgetRegime.PER_TOKEN),
    )


def _build_b_turn_inputs(
    ws: WorkspaceConfig,
    layout: WorkspaceLayout,
    *,
    worktree_path: Path,
    process: ProcessSettings | None = None,
) -> tuple[TriageResult, ToolSet, ToolExecutor, ToolContext, ResolvedTierBModel]:
    """Assemble the ``run_b_turn`` input bundle for a local evolution run.

    Constructs a synthetic ``TriageResult`` with the pinned tool allowlist (L5),
    builds a live ``ToolExecutor`` + ``ToolSet`` via ``build_session_registry``,
    creates a minimal ``ToolContext`` with the worktree as ``workspace_path``, and
    resolves the tier-B transport bundle.

    The pinned tools are set on ``triage.tools`` with ``full_index=False`` so the
    harness never widens them via a re-triage (L5 rule).

    Args:
        ws (WorkspaceConfig): Workspace config.
        layout (WorkspaceLayout): Workspace layout.
        worktree_path (Path): Worktree checkout path (becomes ``workspace_path``).
        process (ProcessSettings | None): Optional process settings; defaults to
            a freshly instantiated ``ProcessSettings()``.

    Returns:
        tuple: ``(triage, tool_set, tool_executor, tool_context, transport_bundle)``.

    Examples:
        >>> _build_b_turn_inputs.__name__
        '_build_b_turn_inputs'
    """
    proc = process or ProcessSettings()
    pinned = _pinned_tool_names()

    # Synthetic TriageResult: complexity=B, pre-built tool allowlist, no re-triage (L5).
    triage = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="",
        tools=pinned,
        skills=list(_EVOLUTION_SKILLS),
        mcp_servers_required=[],
        confidence=1.0,
        requires_vision=False,
        requires_document=False,
        disregard=False,
        followup_anchor=None,
        permission_scope_narrowing=None,
    )

    # Build executor + tool_set (same path as gateway but evolution-scoped).
    tool_executor, tool_set = build_session_registry(
        workspace_config=ws,
        workspace_root=worktree_path,
        layout=layout,
    )

    # Minimal ToolContext: workspace_path = worktree, allow-all permissions.
    session_id = f"evolution-local-{uuid.uuid4().hex[:8]}"
    tool_context = ToolContext(
        session_id=session_id,
        workspace_path=worktree_path,
        workspace_id=str(worktree_path),
        registry_version=tool_set.registry_version,
        permissions=AllowAllPermissionPolicy(),
    )

    transport_bundle = _build_transport_bundle(ws, proc)

    return triage, tool_set, tool_executor, tool_context, transport_bundle


async def dispatch_local_implement(
    conn: sqlite3.Connection,
    ws: WorkspaceConfig,
    layout: WorkspaceLayout,
    issue: EvolutionIssue,
    *,
    session_key: str = "",
    repo_root: Path | None = None,
    fanout: EvolutionIssueEventFanoutFn | None = None,
    process: ProcessSettings | None = None,
) -> EvolutionIssue:
    """Implement an issue in its worktree using the tier-B harness (FL-4A).

    Reads ``worktree_lease.path`` off the issue layout, assembles a ``run_b_turn``
    input bundle with a **pinned tool allowlist** (L5 — ``full_index=False``), runs
    the tier-B executor with a budget of ``local_implement_max_turns``, then returns
    the updated issue.

    The worktree **must** already have been allocated by ``allocate_worktree`` before
    calling this function.

    Args:
        conn (sqlite3.Connection): Workspace SQLite (for future use / consistency with
            sibling dispatchers).
        ws (WorkspaceConfig): Parsed workspace config.
        layout (WorkspaceLayout): Workspace layout.
        issue (EvolutionIssue): Issue being implemented.  Must be ``kind == "bug"`` or
            ``kind == "feature"``; must have an active worktree lease.
        session_key (str): Optional session key for attribution.
        repo_root (Path | None): Sevn.bot checkout root for playbook loading.
        fanout (EvolutionIssueEventFanoutFn | None): Optional event publisher.
        process (ProcessSettings | None): Optional process settings for transport;
            defaults to ``ProcessSettings()``.

    Returns:
        EvolutionIssue: Updated issue (state = ``"implementing"``).

    Raises:
        WorktreeError: When no worktree lease exists for this issue.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(dispatch_local_implement)
        True
    """
    _ = conn  # reserved for future DB writes
    _ = session_key

    lease = load_worktree_lease(layout, issue.id)
    if lease is None:
        msg = f"dispatch_local_implement: no worktree lease for issue {issue.id}"
        raise WorktreeError(msg)

    worktree_path = Path(lease.path)

    pipeline_cfg = effective_my_sevn_pipelines(ws)
    max_rounds = pipeline_cfg.local_implement_max_turns

    prompt = _build_implement_prompt(
        ws,
        layout,
        issue,
        worktree_path=worktree_path,
        repo_root=repo_root,
    )

    logger.info(
        "dispatch_local_implement: issue={} kind={} worktree={} max_rounds={}",
        issue.id,
        issue.kind,
        worktree_path,
        max_rounds,
    )

    triage, tool_set, tool_executor, tool_context, transport_bundle = _build_b_turn_inputs(
        ws,
        layout,
        worktree_path=worktree_path,
        process=process,
    )

    turn_id = f"evo-local-{issue.id}-{uuid.uuid4().hex[:8]}"
    session = SessionHandle(session_id=turn_id)

    outcome = await run_b_turn(
        workspace=ws,
        session=session,
        turn_id=turn_id,
        triage=triage,
        incoming_text=prompt,
        tool_set=tool_set,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=tool_executor,
        transport_bundle=transport_bundle,
        trace=None,
        steer_buffer=None,
        tool_context=tool_context,
        max_rounds=max_rounds,
        full_index=False,
    )

    logger.info(
        "dispatch_local_implement: done issue={} status={} rounds={}",
        issue.id,
        outcome.status,
        outcome.rounds_used,
    )

    # Record that implement completed; keep state=implementing so run_ci_smoke can proceed.
    line = (
        f"Local tier-B implement completed (status={outcome.status}, rounds={outcome.rounds_used})."
    )
    issue = set_issue_stage(
        layout,
        issue,
        state="implementing",
        pipeline_stage="implementing",
        log_line=line,
    )
    await publish_transition(fanout, issue=issue, line=line)
    return issue


__all__ = ["dispatch_local_implement"]
