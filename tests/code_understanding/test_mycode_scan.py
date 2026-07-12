"""Tests for the deterministic MYCODE repository walker."""

from __future__ import annotations

from pathlib import Path

from sevn.code_understanding.mycode_scan import scan_repo


def _by_path(digest_files: list, path: str) -> object | None:
    for entry in digest_files:
        if entry.path == path:
            return entry
    return None


def test_scan_repo_picks_up_python_symbols(tmp_path: Path) -> None:
    py = tmp_path / "alpha.py"
    py.write_text(
        "import os\n"
        "from collections import deque\n\n"
        "class Alpha:\n"
        "    pass\n\n"
        "def beta(x: int) -> int:\n"
        "    return x\n",
        encoding="utf-8",
    )

    digest = scan_repo(tmp_path, [])

    entry = _by_path(digest.files, "alpha.py")
    assert entry is not None
    assert entry.language == "python"
    assert "Alpha" in entry.symbols
    assert "beta" in entry.symbols
    assert "os" in entry.imports
    assert "collections" in entry.imports


def test_scan_repo_handles_typescript(tmp_path: Path) -> None:
    (tmp_path / "x.ts").write_text(
        "export class Widget {}\nexport function ping() { return 1; }\n",
        encoding="utf-8",
    )

    digest = scan_repo(tmp_path, [])
    entry = _by_path(digest.files, "x.ts")
    assert entry is not None
    assert entry.language == "typescript"
    assert "Widget" in entry.symbols
    assert "ping" in entry.symbols


def test_scan_repo_respects_ignore_patterns(tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("def keep(): return 1\n", encoding="utf-8")
    (tmp_path / "drop.tmp").write_text("temporary", encoding="utf-8")
    nested = tmp_path / "build"
    nested.mkdir()
    (nested / "artifact.py").write_text("# artifact\n", encoding="utf-8")

    digest = scan_repo(tmp_path, ["*.tmp", "build"])

    paths = {entry.path for entry in digest.files}
    assert "keep.py" in paths
    assert "drop.tmp" not in paths
    assert all(not p.startswith("build/") for p in paths)


def test_scan_repo_respects_gitignore_in_real_repo(tmp_path: Path) -> None:
    """With a real git checkout, gitignored trees on disk are never indexed."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")

    def _write(rel: str, text: str) -> None:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    _write("src/sevn/mod.py", "def real(): return 1\n")
    _write(".gitignore", "legacy/\nplan/\nreports/\n")
    # Gitignored trees that exist on disk but must never be indexed:
    _write("legacy/secret.py", "def leaked(): return 1\n")
    _write("plan/design.md", "# local design doc\n")
    _write("reports/audit/plan.json", "{}\n")
    git("add", "src/sevn/mod.py", ".gitignore")

    digest = scan_repo(repo, [])

    paths = {entry.path for entry in digest.files}
    # Tracked files are indexed:
    assert "src/sevn/mod.py" in paths
    assert ".gitignore" in paths
    # Gitignored, on disk, but excluded because untracked:
    assert not any(p.startswith("legacy/") for p in paths)
    assert not any(p.startswith("plan/") for p in paths)
    assert not any(p.startswith("reports/") for p in paths)


def test_scan_repo_marks_unknown_language(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello\nworld\n", encoding="utf-8")

    digest = scan_repo(tmp_path, [])

    entry = _by_path(digest.files, "notes.txt")
    assert entry is not None
    assert entry.language == "other"
    assert entry.line_count == 2
