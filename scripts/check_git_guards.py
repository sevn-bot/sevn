#!/usr/bin/env python3
"""Fail when sevn.bot git clean guard is missing or ineffective.

Module: scripts.check_git_guards
Depends: os, pathlib, subprocess, sys

Exports:
    main — exit 1 when ``bin/git`` does not block ``git clean -x/-X``.

Examples:
    >>> isinstance(REPO, Path)
    True
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _git_real_path_file(repo: Path) -> Path:
    """Return path to ``sevn-real-git-path`` for main checkout or linked worktree.

    Args:
        repo (Path): Repository root.

    Returns:
        Path: Expected marker file written by ``make install-git-guards``.

    Examples:
        >>> _git_real_path_file(REPO).name
        'sevn-real-git-path'
    """
    git_file = repo / ".git"
    if git_file.is_file():
        for line in git_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("gitdir:"):
                git_dir = Path(stripped.split(":", 1)[1].strip())
                return git_dir / "sevn-real-git-path"
    return repo / ".git" / "sevn-real-git-path"


def main() -> int:
    """Exit 1 when bin/git guard does not block clean -x/-X.

    Returns:
        int: ``0`` when guard works; ``1`` otherwise.

    Examples:
        >>> main() in (0, 1)
        True
    """
    repo = REPO
    bin_git = repo / "bin" / "git"
    if not bin_git.is_file():
        print(
            "check-git-guards: FAIL — missing bin/git (run make install-git-guards)",
            file=sys.stderr,
        )
        return 1
    real_path = _git_real_path_file(repo)
    if not real_path.is_file():
        print(
            "check-git-guards: FAIL — missing .git/sevn-real-git-path (run make install-git-guards)",
            file=sys.stderr,
        )
        return 1

    env = os.environ.copy()
    env["PATH"] = f"{repo / 'bin'}:{env.get('PATH', '')}"
    probe = subprocess.run(
        ["git", "clean", "-fdx", "--dry-run"],
        check=False,
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
    )
    if probe.returncode == 0:
        print("check-git-guards: FAIL — git clean -fdx was not blocked", file=sys.stderr)
        return 1
    combined = probe.stderr + probe.stdout
    if "BLOCKED" not in combined:
        print("check-git-guards: FAIL — guard did not emit BLOCKED", file=sys.stderr)
        return 1
    print("check-git-guards: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
