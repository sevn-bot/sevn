"""Full-repo mirror into ``workspace/source_code/`` (`src/sevn/workspace/source_copy.py`)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sevn.workspace import source_copy
from sevn.workspace.source_copy import sync_source_copy

if TYPE_CHECKING:
    import pytest


def _write(path: Path, text: str = "x") -> None:
    """Create ``path`` and any parents, writing ``text``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_repo(root: Path) -> None:
    """Build a multi-directory fixture checkout with junk and git-ignored trees."""
    _write(root / "Makefile", "all:\n")
    _write(root / "pyproject.toml", "[project]\nname = 'sevn'\n")
    _write(root / "src" / "sevn" / "gateway" / "agent_turn.py", "# turn\n")
    _write(root / "about-sevn.bot" / "ARCHITECTURE.md", "# arch\n")
    _write(root / "tests" / "test_x.py", "def test_x(): ...\n")
    # Excluded trees / junk:
    _write(root / "specs" / "28-code-understanding.md", "# spec\n")
    _write(root / "prd" / "08.md", "# prd\n")
    _write(root / ".git" / "config", "[core]\n")
    _write(root / ".venv" / "pyvenv.cfg", "home = /x\n")
    _write(root / "node_modules" / "pkg" / "index.js", "module.exports = {}\n")
    _write(root / "src" / "sevn" / "__pycache__" / "x.cpython-312.pyc", "bytecode")
    _write(root / "src" / "sevn" / "gateway" / "stale.pyc", "bytecode")
    # Heavy / cache / nested-checkout trees that must never be mirrored:
    _write(root / ".worktrees" / "feat" / "src" / "sevn" / "dup.py", "# worktree copy\n")
    _write(root / ".sevn" / "workspace" / "state.json", "{}\n")
    _write(root / ".index" / "mycode" / "MYCODE.md", "# huge index\n")
    _write(root / "graphify-out" / "graph.json", "{}\n")


def test_sync_mirrors_full_repo_minus_excludes(tmp_path: Path) -> None:
    """The mirror copies the whole tree except junk, .git, and specs/prd."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    written = sync_source_copy(workspace, repo)
    assert written > 0

    mirror = workspace / "source_code"
    # Included content:
    assert (mirror / "Makefile").is_file()
    assert (mirror / "pyproject.toml").is_file()
    assert (mirror / "src" / "sevn" / "gateway" / "agent_turn.py").is_file()
    assert (mirror / "about-sevn.bot" / "ARCHITECTURE.md").is_file()
    assert (mirror / "tests" / "test_x.py").is_file()

    # Excluded content:
    assert not (mirror / "specs").exists()
    assert not (mirror / "prd").exists()
    assert not (mirror / ".git").exists()
    assert not (mirror / ".venv").exists()
    assert not (mirror / "node_modules").exists()
    assert not (mirror / "src" / "sevn" / "__pycache__").exists()
    assert not (mirror / "src" / "sevn" / "gateway" / "stale.pyc").exists()
    # Heavy / cache / nested-checkout trees stay out of the mirror:
    assert not (mirror / ".worktrees").exists()
    assert not (mirror / ".sevn").exists()
    assert not (mirror / ".index").exists()
    assert not (mirror / "graphify-out").exists()


def test_sync_never_recurses_the_mirror(tmp_path: Path) -> None:
    """``source_code`` under the repo (or workspace) is not re-mirrored into itself."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    _write(repo / "source_code" / "leaked.txt", "should be skipped")
    workspace = tmp_path / "ws"
    workspace.mkdir()

    sync_source_copy(workspace, repo)

    assert not (workspace / "source_code" / "source_code").exists()
    assert not (workspace / "source_code" / "leaked.txt").exists()


def test_sync_prunes_deleted_files(tmp_path: Path) -> None:
    """A file removed from the source disappears from the mirror on the next sync."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    sync_source_copy(workspace, repo)
    target = workspace / "source_code" / "src" / "sevn" / "gateway" / "agent_turn.py"
    assert target.is_file()

    (repo / "src" / "sevn" / "gateway" / "agent_turn.py").unlink()
    sync_source_copy(workspace, repo)
    assert not target.exists()


def test_sync_is_incremental_no_op(tmp_path: Path) -> None:
    """A second sync with no source changes rewrites nothing."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    sync_source_copy(workspace, repo)
    assert sync_source_copy(workspace, repo) == 0


def test_sync_missing_repo_returns_zero(tmp_path: Path) -> None:
    """A nonexistent repo root is a no-op."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    assert sync_source_copy(workspace, tmp_path / "nope") == 0


def test_sync_respects_gitignore_in_real_repo(tmp_path: Path) -> None:
    """With a real git checkout, gitignored trees on disk are never mirrored."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    _write(repo / "src" / "sevn" / "mod.py", "# real source\n")
    _write(repo / ".gitignore", "legacy/\nplan/\nreports/\n")
    # Gitignored trees that exist on disk but must never reach the mirror:
    _write(repo / "legacy" / "secret.py", "# private reference code\n")
    _write(repo / "plan" / "design.md", "# local design doc\n")
    _write(repo / "reports" / "audit" / "plan.json", "{}\n")
    git("add", "src/sevn/mod.py", ".gitignore")

    workspace = tmp_path / "ws"
    workspace.mkdir()
    sync_source_copy(workspace, repo)

    mirror = workspace / "source_code"
    assert (mirror / "src" / "sevn" / "mod.py").is_file()
    assert (mirror / ".gitignore").is_file()
    # Gitignored, on disk, but excluded because untracked:
    assert not (mirror / "legacy").exists()
    assert not (mirror / "plan").exists()
    assert not (mirror / "reports").exists()


def test_sync_stops_at_file_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repo that exceeds the file ceiling is aborted instead of filling the disk."""
    from loguru import logger

    monkeypatch.setattr(source_copy, "_MAX_MIRROR_FILES", 3)
    repo = tmp_path / "repo"
    for i in range(20):
        _write(repo / "src" / f"mod_{i}.py", f"# {i}\n")
    workspace = tmp_path / "ws"
    workspace.mkdir()

    messages: list[str] = []
    sink_id = logger.add(messages.append, level="WARNING")
    try:
        written = sync_source_copy(workspace, repo)
    finally:
        logger.remove(sink_id)

    mirror = workspace / "source_code"
    mirrored = list(mirror.rglob("*.py"))
    assert len(mirrored) <= 3  # stopped well short of the 20 source files
    assert written <= 3
    assert any("safety ceiling" in m for m in messages)


def test_sync_skips_nested_mirror_inside_repo(tmp_path: Path) -> None:
    """When the mirror lives inside the repo, it is never copied into itself."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    # workspace content root sits *inside* the repo, so source_code/ is under repo.
    workspace = repo / "nested_ws"
    workspace.mkdir()

    sync_source_copy(workspace, repo)
    mirror = workspace / "source_code"

    assert (mirror / "src" / "sevn" / "gateway" / "agent_turn.py").is_file()
    assert not (mirror / "nested_ws" / "source_code").exists()
