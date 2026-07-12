"""Promotion step tests (`plan/full-loop-evolution-wave-plan.md` FL-3.4)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.evolution.issues import create_issue, save_issue
from sevn.evolution.promotion import PromotionError, promote_issue
from sevn.evolution.worktree import WorktreeError, allocate_worktree
from sevn.integrations.github_skill.hooks import GithubSkillHooks, integration_call_from_mapping
from sevn.workspace.layout import WorkspaceLayout

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_git_repo(path: Path) -> None:
    """Initialise a minimal git repo with one commit."""
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "promo@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Promotion Test"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


def _layout(tmp_path: Path) -> tuple[WorkspaceLayout, WorkspaceConfig]:
    tmp_path.mkdir(parents=True, exist_ok=True)
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


def _hooks(responses: dict[str, object]) -> GithubSkillHooks:
    client: dict[str, object] = {"calls": [], "responses": responses}
    return GithubSkillHooks(integration_call=integration_call_from_mapping(client))


def _make_commit(checkout: Path) -> None:
    """Add a new commit to the worktree checkout."""
    (checkout / "change.txt").write_text("change\n", encoding="utf-8")
    subprocess.run(["git", "add", "change.txt"], cwd=checkout, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "implement fix"],
        cwd=checkout,
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# FL-3.4.A — no-commits aborts before push/PR
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promote_issue_aborts_when_no_commits(tmp_path: Path) -> None:
    """Worktree with no commits ahead of base raises PromotionError — no push, no PR."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    lay, _ws = _layout(tmp_path / "ws")

    issue = create_issue(lay, kind="bug", title="No-commit bug", state="implementing")
    save_issue(lay, issue)

    allocate_worktree(lay, issue.id, repo_root=repo, executor="local")

    hooks = _hooks({})
    called: list[str] = []

    async def _fake_push(*_a: object, **_kw: object) -> None:
        called.append("push")

    async def _fake_pr(*_a: object, **_kw: object) -> dict[str, object]:
        called.append("pr")
        return {}

    with (
        patch("sevn.evolution.promotion._git", wraps=lambda cwd, *args: _real_git(cwd, *args)),
        patch(
            "sevn.evolution.promotion.create_pull_request",
            new_callable=AsyncMock,
            side_effect=_fake_pr,
        ),
        pytest.raises(PromotionError, match="no commits ahead"),
    ):
        await promote_issue(lay, issue, hooks=hooks, repo="o/r")

    assert "push" not in called
    assert "pr" not in called


def _real_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Delegate back to real git for the no-commit test."""
    import shutil

    git_bin = shutil.which("git") or "git"
    return subprocess.run([git_bin, *args], cwd=cwd, capture_output=True, text=True, check=False)


# ---------------------------------------------------------------------------
# FL-3.4.B — dry-run opens no PR, advances stage to promote/done
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promote_issue_dry_run_opens_no_pr(tmp_path: Path) -> None:
    """promotion_dry_run=True skips push and PR; stage advances to promote/done."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    lay, _ws = _layout(tmp_path / "ws")

    issue = create_issue(lay, kind="bug", title="Dry-run bug", state="implementing")
    save_issue(lay, issue)

    allocate_worktree(lay, issue.id, repo_root=repo, executor="local")

    pr_called: list[str] = []

    async def _fake_pr(*_a: object, **_kw: object) -> dict[str, object]:
        pr_called.append("pr")
        return {}

    hooks = GithubSkillHooks()

    with patch(
        "sevn.evolution.promotion.create_pull_request", new_callable=AsyncMock, side_effect=_fake_pr
    ):
        result = await promote_issue(lay, issue, hooks=hooks, repo="o/r", promotion_dry_run=True)

    assert result.pipeline_stage == "promote/done"
    assert result.state == "done"
    assert pr_called == []  # no PR opened


# ---------------------------------------------------------------------------
# FL-3.4.C — success path: pr_url persisted and stage set to promote/done
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promote_issue_persists_pr_url(tmp_path: Path) -> None:
    """Worktree with commits ahead: pushes, opens PR, persists pr_url + promote/done."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    lay, _ws = _layout(tmp_path / "ws")

    issue = create_issue(lay, kind="bug", title="Real bug fix", state="implementing")
    save_issue(lay, issue)

    lease = allocate_worktree(lay, issue.id, repo_root=repo, executor="local")

    # Add a commit so there is something to promote.
    _make_commit(Path(lease.path))

    hooks = _hooks({"pulls.create": {"number": 99, "html_url": "https://github.com/o/r/pull/99"}})

    with patch(
        "sevn.evolution.promotion._git",
        side_effect=lambda cwd, *args: _fake_git_success(cwd, *args),
    ):
        result = await promote_issue(lay, issue, hooks=hooks, repo="o/r")

    assert result.pr_url == "https://github.com/o/r/pull/99"
    assert result.pipeline_stage == "promote/done"
    assert result.state == "done"


def _fake_git_success(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Return success for push; delegate rev-list to real git."""
    if args and args[0] == "push":
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")
    return _real_git(cwd, *args)


# ---------------------------------------------------------------------------
# FL-3.4.D — missing worktree lease raises WorktreeError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promote_issue_no_lease_raises(tmp_path: Path) -> None:
    """promote_issue raises WorktreeError when no worktree lease exists."""
    lay, _ws = _layout(tmp_path / "ws")
    issue = create_issue(lay, kind="bug", title="No lease", state="implementing")
    save_issue(lay, issue)

    hooks = GithubSkillHooks()
    with pytest.raises(WorktreeError, match="no worktree lease"):
        await promote_issue(lay, issue, hooks=hooks, repo="o/r")


# ---------------------------------------------------------------------------
# FL-3.4.E — push failure raises PromotionError (no PR opened)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promote_issue_push_failure_raises(tmp_path: Path) -> None:
    """A failing git push raises PromotionError before the PR is attempted."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    lay, _ws = _layout(tmp_path / "ws")

    issue = create_issue(lay, kind="bug", title="Push failure", state="implementing")
    save_issue(lay, issue)

    lease = allocate_worktree(lay, issue.id, repo_root=repo, executor="local")
    _make_commit(Path(lease.path))

    pr_called: list[str] = []

    async def _fake_pr(*_a: object, **_kw: object) -> dict[str, object]:
        pr_called.append("pr")
        return {}

    hooks = GithubSkillHooks()

    with (
        patch(
            "sevn.evolution.promotion._git",
            side_effect=lambda cwd, *args: _fake_git_push_fail(cwd, *args),
        ),
        patch(
            "sevn.evolution.promotion.create_pull_request",
            new_callable=AsyncMock,
            side_effect=_fake_pr,
        ),
        pytest.raises(PromotionError, match="push failed"),
    ):
        await promote_issue(lay, issue, hooks=hooks, repo="o/r")

    assert pr_called == []


def _fake_git_push_fail(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Simulate a failed git push; let other git commands run normally."""
    if args and args[0] == "push":
        return subprocess.CompletedProcess(
            args=list(args), returncode=1, stdout="", stderr="remote: permission denied"
        )
    return _real_git(cwd, *args)
