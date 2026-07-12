"""``sevn sync`` repository resolution and git policy (`specs/23-cli.md` §2.4.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.cli.repo_sync import (
    SYNC_TRACKING_BRANCH,
    RepoSyncError,
    resolve_sevn_repo_root,
    sync_source_tree,
)


def _write_sevn_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    (path / "pyproject.toml").write_text('[project]\nname = "sevn"\n', encoding="utf-8")


def _write_bound_workspace(home: Path, repo_path: Path) -> None:
    ws = home / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "sevn.json").write_text(
        json.dumps({"schema_version": 1, "my_sevn": {"repo_path": str(repo_path)}}),
        encoding="utf-8",
    )


def test_resolve_repo_from_explicit_path(tmp_path: Path) -> None:
    root = tmp_path / "sevn.bot"
    _write_sevn_repo(root)
    assert resolve_sevn_repo_root(root) == root.resolve()


def test_resolve_repo_prefers_workspace_repo_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``my_sevn.repo_path`` (the gateway's tree) wins over the current directory.

    Reproduces the two-clone split: ``sevn sync`` invoked from a *different* checkout must
    still target the configured repo, not whatever clone cwd happens to sit in.
    """
    gateway_tree = tmp_path / "gateway-clone"
    _write_sevn_repo(gateway_tree)
    other_clone = tmp_path / "other-clone"
    _write_sevn_repo(other_clone)
    home = tmp_path / "home"
    _write_bound_workspace(home, gateway_tree)
    monkeypatch.delenv("SEVN_REPO_ROOT", raising=False)
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.chdir(other_clone)
    assert resolve_sevn_repo_root() == gateway_tree.resolve()


def test_resolve_repo_env_overrides_workspace_repo_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``SEVN_REPO_ROOT`` still takes precedence over the configured ``repo_path``."""
    configured = tmp_path / "configured"
    _write_sevn_repo(configured)
    forced = tmp_path / "forced"
    _write_sevn_repo(forced)
    home = tmp_path / "home"
    _write_bound_workspace(home, configured)
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_REPO_ROOT", str(forced))
    assert resolve_sevn_repo_root() == forced.resolve()


def test_resolve_repo_falls_back_to_cwd_when_repo_path_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale/missing ``repo_path`` is ignored; resolution walks up from cwd."""
    home = tmp_path / "home"
    _write_bound_workspace(home, tmp_path / "does-not-exist")
    cwd_repo = tmp_path / "cwd-clone"
    _write_sevn_repo(cwd_repo)
    monkeypatch.delenv("SEVN_REPO_ROOT", raising=False)
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.chdir(cwd_repo)
    assert resolve_sevn_repo_root() == cwd_repo.resolve()


def test_resolve_repo_rejects_missing_git(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "sevn"\n', encoding="utf-8")
    with pytest.raises(RepoSyncError, match=r"not a sevn\.bot"):
        resolve_sevn_repo_root(root)


def test_sync_skips_when_already_up_to_date(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sevn.bot"
    _write_sevn_repo(root)
    rev = "abc123"
    calls: list[tuple[str, ...]] = []

    def fake_git(repo_root: Path, *args: str, dry_run: bool = False) -> str:
        calls.append(args)
        if args == ("rev-parse", "HEAD"):
            return rev
        if args == ("rev-parse", "origin/test-pre"):
            return rev
        if args[:2] == ("merge-base", "--is-ancestor"):
            return ""
        return ""

    monkeypatch.setattr("sevn.cli.repo_sync._git", fake_git)
    monkeypatch.setattr("sevn.cli.repo_sync._is_ancestor", lambda *a, **k: True)
    monkeypatch.setattr("sevn.cli.repo_sync._run_sync_cli", lambda *a, **k: None)

    result = sync_source_tree(repo_root=root, latest=False)
    assert result.updated is False
    assert "already up to date" in result.detail
    assert not any(arg[:2] == ("merge", "--ff-only") for arg in calls)


def test_sync_ff_when_behind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sevn.bot"
    _write_sevn_repo(root)
    local, remote = "localrev", "remoterev"
    merged: list[str] = []

    def fake_git(repo_root: Path, *args: str, dry_run: bool = False) -> str:
        if args == ("rev-parse", "HEAD"):
            return local if not merged else remote
        if args == ("rev-parse", "origin/test-pre"):
            return remote
        if args == ("branch", "--list", SYNC_TRACKING_BRANCH):
            return f"  {SYNC_TRACKING_BRANCH}\n"
        if args == ("checkout", SYNC_TRACKING_BRANCH):
            return ""
        if args == ("merge", "--ff-only", "origin/test-pre"):
            merged.append("ok")
            return ""
        return ""

    monkeypatch.setattr("sevn.cli.repo_sync._git", fake_git)
    monkeypatch.setattr(
        "sevn.cli.repo_sync._is_ancestor",
        lambda repo, older, newer, dry_run=False: older == local and newer == remote,
    )
    setup_called: list[Path] = []
    monkeypatch.setattr(
        "sevn.cli.repo_sync._run_sync_cli",
        lambda repo, dry_run=False: setup_called.append(repo),
    )
    monkeypatch.setattr("sevn.cli.repo_sync._maybe_restart_gateway", lambda **k: None)

    result = sync_source_tree(repo_root=root, latest=False)
    assert result.updated is True
    assert setup_called == [root]


def test_sync_latest_resets_when_diverged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sevn.bot"
    _write_sevn_repo(root)
    reset: list[str] = []

    def fake_git(repo_root: Path, *args: str, dry_run: bool = False) -> str:
        if args == ("rev-parse", "HEAD"):
            return "local"
        if args == ("rev-parse", "origin/test-pre"):
            return "remote"
        if args == ("branch", "--list", SYNC_TRACKING_BRANCH):
            return ""
        if args[0] == "checkout":
            return ""
        if args[:2] == ("reset", "--hard"):
            reset.append(args[2])
            return ""
        return ""

    monkeypatch.setattr("sevn.cli.repo_sync._git", fake_git)
    monkeypatch.setattr("sevn.cli.repo_sync._is_ancestor", lambda *a, **k: False)
    monkeypatch.setattr("sevn.cli.repo_sync._run_sync_cli", lambda *a, **k: None)
    monkeypatch.setattr("sevn.cli.repo_sync._maybe_restart_gateway", lambda **k: None)

    sync_source_tree(repo_root=root, latest=True)
    assert reset == ["origin/test-pre"]


def test_sync_latest_resets_when_behind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sevn.bot"
    _write_sevn_repo(root)
    local, remote = "localrev", "remoterev"
    reset: list[str] = []

    def fake_git(repo_root: Path, *args: str, dry_run: bool = False) -> str:
        if args == ("rev-parse", "HEAD"):
            return local if not reset else remote
        if args == ("rev-parse", "origin/test-pre"):
            return remote
        if args == ("branch", "--list", SYNC_TRACKING_BRANCH):
            return f"  {SYNC_TRACKING_BRANCH}\n"
        if args[0] == "checkout":
            return ""
        if args[:2] == ("reset", "--hard"):
            reset.append(args[2])
            return ""
        return ""

    monkeypatch.setattr("sevn.cli.repo_sync._git", fake_git)
    monkeypatch.setattr(
        "sevn.cli.repo_sync._is_ancestor",
        lambda repo, older, newer, dry_run=False: older == local and newer == remote,
    )
    monkeypatch.setattr("sevn.cli.repo_sync._run_sync_cli", lambda *a, **k: None)
    monkeypatch.setattr("sevn.cli.repo_sync._maybe_restart_gateway", lambda **k: None)

    result = sync_source_tree(repo_root=root, latest=True)
    assert reset == ["origin/test-pre"]
    assert result.updated is True


def test_sync_latest_reruns_sync_cli_when_already_up_to_date(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sevn.bot"
    _write_sevn_repo(root)
    rev = "abc123"
    sync_cli_called: list[Path] = []

    def fake_git(repo_root: Path, *args: str, dry_run: bool = False) -> str:
        if args == ("rev-parse", "HEAD"):
            return rev
        if args == ("rev-parse", "origin/test-pre"):
            return rev
        if args == ("branch", "--list", SYNC_TRACKING_BRANCH):
            return f"  {SYNC_TRACKING_BRANCH}\n"
        if args[0] == "checkout":
            return ""
        if args[:2] == ("reset", "--hard"):
            return ""
        return ""

    monkeypatch.setattr("sevn.cli.repo_sync._git", fake_git)
    monkeypatch.setattr("sevn.cli.repo_sync._is_ancestor", lambda *a, **k: True)
    monkeypatch.setattr(
        "sevn.cli.repo_sync._run_sync_cli",
        lambda repo, dry_run=False: sync_cli_called.append(repo),
    )
    monkeypatch.setattr("sevn.cli.repo_sync._maybe_restart_gateway", lambda **k: None)

    result = sync_source_tree(repo_root=root, latest=True)
    assert sync_cli_called == [root]
    assert result.updated is True


def test_sync_latest_runs_logo_mark_animate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sevn.bot"
    _write_sevn_repo(root)
    animate_called: list[Path] = []

    def fake_git(repo_root: Path, *args: str, dry_run: bool = False) -> str:
        if args == ("rev-parse", "HEAD"):
            return "rev"
        if args == ("rev-parse", "origin/test-pre"):
            return "rev"
        if args == ("branch", "--list", SYNC_TRACKING_BRANCH):
            return f"  {SYNC_TRACKING_BRANCH}\n"
        if args[0] == "checkout":
            return ""
        if args[:2] == ("reset", "--hard"):
            return ""
        return ""

    monkeypatch.setattr("sevn.cli.repo_sync._git", fake_git)
    monkeypatch.setattr("sevn.cli.repo_sync._is_ancestor", lambda *a, **k: True)
    monkeypatch.setattr("sevn.cli.repo_sync._run_sync_cli", lambda *a, **k: None)
    monkeypatch.setattr("sevn.cli.repo_sync._maybe_restart_gateway", lambda **k: None)
    monkeypatch.setattr(
        "sevn.cli.repo_sync._maybe_logo_mark_animate",
        lambda repo, latest, dry_run=False: animate_called.append(repo) or "logo-mark-animate",
    )

    result = sync_source_tree(repo_root=root, latest=True)
    assert animate_called == [root]
    assert "logo-mark-animate" in result.detail


def test_sync_skips_logo_mark_animate_without_latest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sevn.bot"
    _write_sevn_repo(root)
    local, remote = "localrev", "remoterev"

    def fake_git(repo_root: Path, *args: str, dry_run: bool = False) -> str:
        if args == ("rev-parse", "HEAD"):
            return local
        if args == ("rev-parse", "origin/test-pre"):
            return remote
        if args == ("branch", "--list", SYNC_TRACKING_BRANCH):
            return f"  {SYNC_TRACKING_BRANCH}\n"
        if args == ("checkout", SYNC_TRACKING_BRANCH):
            return ""
        if args == ("merge", "--ff-only", "origin/test-pre"):
            return ""
        return ""

    monkeypatch.setattr("sevn.cli.repo_sync._git", fake_git)
    monkeypatch.setattr(
        "sevn.cli.repo_sync._is_ancestor",
        lambda repo, older, newer, dry_run=False: older == local and newer == remote,
    )
    monkeypatch.setattr("sevn.cli.repo_sync._run_sync_cli", lambda *a, **k: None)
    monkeypatch.setattr("sevn.cli.repo_sync._maybe_restart_gateway", lambda **k: None)
    animate_attempts: list[bool] = []
    monkeypatch.setattr(
        "sevn.cli.repo_sync._maybe_logo_mark_animate",
        lambda *a, **k: animate_attempts.append(True),
    )

    sync_source_tree(repo_root=root, latest=False)
    assert animate_attempts == []


def test_sync_refreshes_workspace_skills_after_sync_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sevn.bot"
    _write_sevn_repo(root)
    refresh_called: list[bool] = []

    def fake_git(repo_root: Path, *args: str, dry_run: bool = False) -> str:
        if args == ("rev-parse", "HEAD"):
            return "rev"
        if args == ("rev-parse", "origin/test-pre"):
            return "rev"
        if args == ("branch", "--list", SYNC_TRACKING_BRANCH):
            return f"  {SYNC_TRACKING_BRANCH}\n"
        if args[0] == "checkout":
            return ""
        if args[:2] == ("reset", "--hard"):
            return ""
        return ""

    monkeypatch.setattr("sevn.cli.repo_sync._git", fake_git)
    monkeypatch.setattr("sevn.cli.repo_sync._is_ancestor", lambda *a, **k: True)
    monkeypatch.setattr("sevn.cli.repo_sync._run_sync_cli", lambda *a, **k: None)
    monkeypatch.setattr("sevn.cli.repo_sync._maybe_restart_gateway", lambda **k: None)
    monkeypatch.setattr(
        "sevn.cli.repo_sync._refresh_workspace_skills",
        lambda **k: refresh_called.append(True) or "refreshed skills/core (1): pdf",
    )

    result = sync_source_tree(repo_root=root, latest=True)
    assert refresh_called == [True]
    assert "refreshed skills/core" in result.detail
