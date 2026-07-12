"""Worktree lease tests (`specs/35-bot-evolution.md` EV-5)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.evolution.worktree import (
    WorktreeError,
    allocate_worktree,
    code_worktrees_dir,
    load_worktree_lease,
    promote_worktree,
    run_ci_smoke,
)
from sevn.workspace.layout import WorkspaceLayout


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "ev@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Evolution Test"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


def _layout(tmp_path: Path) -> WorkspaceLayout:
    tmp_path.mkdir(parents=True, exist_ok=True)
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    return WorkspaceLayout.from_config(
        sevn_json,
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
    )


def test_allocate_worktree_and_ci_smoke(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    lay = _layout(tmp_path / "ws")
    lease = allocate_worktree(lay, "issue-1", repo_root=repo, executor="local")
    assert Path(lease.path).is_dir()
    assert load_worktree_lease(lay, "issue-1") is not None
    meta = json.loads(
        (code_worktrees_dir(lay) / "issue-1" / "meta.json").read_text(encoding="utf-8")
    )
    assert meta["issue_id"] == "issue-1"
    smoke = run_ci_smoke(Path(lease.path), dry_run=True)
    assert smoke.ok is True
    promo = promote_worktree(
        lay,
        "issue-1",
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
        dry_run=True,
    )
    assert promo["mode"] == "pr"


def test_allocate_rejects_duplicate_lease(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    lay = _layout(tmp_path / "ws")
    first = allocate_worktree(lay, "dup", repo_root=repo)
    second = allocate_worktree(lay, "dup", repo_root=repo)
    assert first.path == second.path
    occupied = code_worktrees_dir(lay) / "blocked" / "checkout"
    occupied.mkdir(parents=True)
    with pytest.raises(WorktreeError, match="checkout path already exists"):
        allocate_worktree(lay, "blocked", repo_root=repo)
