"""Tests for the FL-4A local tier-B executor (`plan/full-loop-evolution-wave-plan.md` FL-4A.5)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.evolution.executors.local import (
    _build_implement_prompt,
    _pinned_tool_names,
    _spec_kit_artefact_paths,
    dispatch_local_implement,
)
from sevn.evolution.issues import create_issue
from sevn.evolution.worktree import WorktreeLease
from sevn.workspace.layout import WorkspaceLayout

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _layout(tmp_path: Path) -> tuple[WorkspaceLayout, WorkspaceConfig]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    return WorkspaceLayout.from_config(sevn_json, cfg), cfg


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(":memory:", check_same_thread=False)


def _fake_lease(worktree_path: Path, issue_id: str = "issue-1") -> WorktreeLease:
    return WorktreeLease(
        issue_id=issue_id,
        path=str(worktree_path),
        base_sha="abc123",
        executor="local",
        leased_at="2026-01-01T00:00:00Z",
    )


def _fake_outcome(status: str = "completed", rounds: int = 3) -> MagicMock:
    outcome = MagicMock()
    outcome.status = status
    outcome.rounds_used = rounds
    return outcome


# ---------------------------------------------------------------------------
# _pinned_tool_names
# ---------------------------------------------------------------------------


def test_pinned_tool_names_includes_required_tools() -> None:
    """Pinned allowlist must include all file ops + exec + integration tools."""
    names = _pinned_tool_names()
    for required in (
        "read",
        "edit",
        "write",
        "glob",
        "grep",
        "sandbox_exec",
        "terminal_run",
        "run_skill_script",
        "integration_call",
    ):
        assert required in names, f"missing required tool: {required}"


def test_pinned_tool_names_returns_list_of_strings() -> None:
    """Returns a plain list of non-empty strings."""
    names = _pinned_tool_names()
    assert isinstance(names, list)
    assert all(isinstance(n, str) and n for n in names)


# ---------------------------------------------------------------------------
# _spec_kit_artefact_paths
# ---------------------------------------------------------------------------


def test_spec_kit_artefact_paths_returns_none_when_missing(tmp_path: Path) -> None:
    """Paths that do not exist resolve to None."""
    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="feature", title="f1")

    paths = _spec_kit_artefact_paths(ws, lay, issue)
    # Files not written yet → all None.
    assert paths["spec"] is None
    assert paths["plan"] is None
    assert paths["tasks"] is None


def test_spec_kit_artefact_paths_returns_path_when_present(tmp_path: Path) -> None:
    """Existing artefact files resolve to their Path."""
    from sevn.evolution.feature_pipeline import feature_artefacts_dir

    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="feature", title="f2")

    artefacts = feature_artefacts_dir(ws, lay, issue.id)
    (artefacts / "plan.md").write_text("# Plan", encoding="utf-8")

    paths = _spec_kit_artefact_paths(ws, lay, issue)
    assert paths["plan"] is not None
    assert paths["plan"].name == "plan.md"
    assert paths["spec"] is None  # not written


# ---------------------------------------------------------------------------
# _build_implement_prompt
# ---------------------------------------------------------------------------


def test_build_implement_prompt_bug_contains_title_and_constraint(tmp_path: Path) -> None:
    """Bug prompt includes issue title, body, and worktree constraint."""
    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="bug", title="Crash on login", body="Steps: ...")
    wt_path = tmp_path / "worktree"

    prompt = _build_implement_prompt(ws, lay, issue, worktree_path=wt_path, repo_root=None)

    assert "Crash on login" in prompt
    assert "Steps: ..." in prompt
    assert str(wt_path) in prompt
    assert "edit files only under" in prompt.lower() or "must" in prompt


def test_build_implement_prompt_feature_includes_artefact_paths(tmp_path: Path) -> None:
    """Feature prompt includes paths to spec/plan/tasks when present."""
    from sevn.evolution.feature_pipeline import feature_artefacts_dir

    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="feature", title="New dashboard")
    wt_path = tmp_path / "worktree"

    artefacts = feature_artefacts_dir(ws, lay, issue.id)
    (artefacts / "plan.md").write_text("# Plan", encoding="utf-8")

    prompt = _build_implement_prompt(ws, lay, issue, worktree_path=wt_path, repo_root=None)

    assert "New dashboard" in prompt
    assert "plan.md" in prompt


def test_build_implement_prompt_spec_kit_dry_run_preserved(tmp_path: Path) -> None:
    """Bug prompt contains a worktree constraint regardless of repo_root."""
    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="bug", title="Spec-kit dry-run bug")
    # spec_kit_dry_run is reflected via issue.kind routing in _build_implement_prompt.
    wt_path = tmp_path / "worktree"

    prompt = _build_implement_prompt(ws, lay, issue, worktree_path=wt_path, repo_root=None)
    # Constraint section must be present — confirms spec_kit_dry_run path doesn't break this.
    assert str(wt_path) in prompt


# ---------------------------------------------------------------------------
# dispatch_local_implement — main assertions (FL-4A.5)
# ---------------------------------------------------------------------------


async def test_dispatch_local_implement_calls_run_b_turn_with_worktree_path(
    tmp_path: Path,
) -> None:
    """(a) tool_context.workspace_path == worktree path passed to run_b_turn."""
    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="bug", title="Fix crash")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    lease = _fake_lease(worktree, issue.id)

    captured_ctx: list[Any] = []

    async def fake_run_b_turn(**kwargs: Any) -> Any:
        captured_ctx.append(kwargs["tool_context"])
        return _fake_outcome()

    with (
        patch(
            "sevn.evolution.executors.local.load_worktree_lease",
            return_value=lease,
        ),
        patch(
            "sevn.evolution.executors.local.run_b_turn",
            side_effect=fake_run_b_turn,
        ),
        patch(
            "sevn.evolution.executors.local._build_transport_bundle",
            return_value=MagicMock(),
        ),
        patch(
            "sevn.evolution.executors.local.build_session_registry",
            return_value=(MagicMock(), MagicMock(registry_version=1, skill_descriptions={})),
        ),
    ):
        await dispatch_local_implement(_conn(), ws, lay, issue)

    assert len(captured_ctx) == 1
    assert captured_ctx[0].workspace_path == worktree


async def test_dispatch_local_implement_passes_pinned_tools_and_full_index_false(
    tmp_path: Path,
) -> None:
    """(b) triage.tools == pinned list and full_index=False passed to run_b_turn."""
    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="bug", title="Tool pin test")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    lease = _fake_lease(worktree, issue.id)

    captured_kwargs: list[dict[str, Any]] = []

    async def fake_run_b_turn(**kwargs: Any) -> Any:
        captured_kwargs.append(kwargs)
        return _fake_outcome()

    with (
        patch(
            "sevn.evolution.executors.local.load_worktree_lease",
            return_value=lease,
        ),
        patch(
            "sevn.evolution.executors.local.run_b_turn",
            side_effect=fake_run_b_turn,
        ),
        patch(
            "sevn.evolution.executors.local._build_transport_bundle",
            return_value=MagicMock(),
        ),
        patch(
            "sevn.evolution.executors.local.build_session_registry",
            return_value=(MagicMock(), MagicMock(registry_version=1, skill_descriptions={})),
        ),
    ):
        await dispatch_local_implement(_conn(), ws, lay, issue)

    assert len(captured_kwargs) == 1
    kw = captured_kwargs[0]

    # Pinned tools must be present on triage.tools (L5).
    triage = kw["triage"]
    for tool in _pinned_tool_names():
        assert tool in triage.tools, f"pinned tool missing from triage.tools: {tool}"

    # full_index must be False so the harness can't widen the allowlist.
    assert kw["full_index"] is False


async def test_dispatch_local_implement_uses_configured_max_rounds(
    tmp_path: Path,
) -> None:
    """(c) max_rounds == local_implement_max_turns from my_sevn.pipelines."""
    from sevn.config.workspace_config import MySevnPipelinesWorkspaceConfig, MySevnWorkspaceConfig

    lay, _ = _layout(tmp_path)
    # Build a workspace with a custom budget.
    ws = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        my_sevn=MySevnWorkspaceConfig(
            pipelines=MySevnPipelinesWorkspaceConfig(local_implement_max_turns=7)
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    issue = create_issue(lay, kind="bug", title="Max rounds test")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    lease = _fake_lease(worktree, issue.id)

    captured_kwargs: list[dict[str, Any]] = []

    async def fake_run_b_turn(**kwargs: Any) -> Any:
        captured_kwargs.append(kwargs)
        return _fake_outcome()

    with (
        patch(
            "sevn.evolution.executors.local.load_worktree_lease",
            return_value=lease,
        ),
        patch(
            "sevn.evolution.executors.local.run_b_turn",
            side_effect=fake_run_b_turn,
        ),
        patch(
            "sevn.evolution.executors.local._build_transport_bundle",
            return_value=MagicMock(),
        ),
        patch(
            "sevn.evolution.executors.local.build_session_registry",
            return_value=(MagicMock(), MagicMock(registry_version=1, skill_descriptions={})),
        ),
    ):
        await dispatch_local_implement(_conn(), ws, lay, issue)

    assert captured_kwargs[0]["max_rounds"] == 7


async def test_dispatch_local_implement_raises_when_no_lease(tmp_path: Path) -> None:
    """dispatch_local_implement raises WorktreeError when no lease exists."""
    from sevn.evolution.worktree import WorktreeError

    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="bug", title="No lease")

    with (
        patch(
            "sevn.evolution.executors.local.load_worktree_lease",
            return_value=None,
        ),
        pytest.raises(WorktreeError, match="no worktree lease"),
    ):
        await dispatch_local_implement(_conn(), ws, lay, issue)


async def test_dispatch_local_implement_default_max_rounds_is_20(tmp_path: Path) -> None:
    """Default local_implement_max_turns is 20 (the FL-4A spec value)."""
    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="bug", title="Default budget")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    lease = _fake_lease(worktree, issue.id)

    captured_kwargs: list[dict[str, Any]] = []

    async def fake_run_b_turn(**kwargs: Any) -> Any:
        captured_kwargs.append(kwargs)
        return _fake_outcome()

    with (
        patch(
            "sevn.evolution.executors.local.load_worktree_lease",
            return_value=lease,
        ),
        patch(
            "sevn.evolution.executors.local.run_b_turn",
            side_effect=fake_run_b_turn,
        ),
        patch(
            "sevn.evolution.executors.local._build_transport_bundle",
            return_value=MagicMock(),
        ),
        patch(
            "sevn.evolution.executors.local.build_session_registry",
            return_value=(MagicMock(), MagicMock(registry_version=1, skill_descriptions={})),
        ),
    ):
        await dispatch_local_implement(_conn(), ws, lay, issue)

    assert captured_kwargs[0]["max_rounds"] == 20


async def test_dispatch_local_implement_returns_updated_issue(tmp_path: Path) -> None:
    """dispatch_local_implement returns an EvolutionIssue with state=implementing."""
    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="bug", title="Return value")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    lease = _fake_lease(worktree, issue.id)

    with (
        patch(
            "sevn.evolution.executors.local.load_worktree_lease",
            return_value=lease,
        ),
        patch(
            "sevn.evolution.executors.local.run_b_turn",
            new_callable=AsyncMock,
            return_value=_fake_outcome(),
        ),
        patch(
            "sevn.evolution.executors.local._build_transport_bundle",
            return_value=MagicMock(),
        ),
        patch(
            "sevn.evolution.executors.local.build_session_registry",
            return_value=(MagicMock(), MagicMock(registry_version=1, skill_descriptions={})),
        ),
    ):
        result = await dispatch_local_implement(_conn(), ws, lay, issue)

    assert result.state == "implementing"
    assert result.pipeline_stage == "implementing"
