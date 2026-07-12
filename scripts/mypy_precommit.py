#!/usr/bin/env python3
"""Pre-commit mypy: full ``src/sevn`` tree, excluding untracked Python paths.

Untracked WIP (e.g. ``src/sevn/evolution/``) must not block commits on other
modules. Pre-commit may stash unstaged edits; untracked files remain on disk
and would otherwise fail typecheck against the indexed ``workspace_config``.
``make typecheck`` / CI still run ``mypy src/sevn`` with no extra excludes.

Module: scripts.mypy_precommit
Depends: re, subprocess, sys, pathlib

Exports:
    main — run mypy on ``src/sevn`` with dynamic excludes for untracked code.

Examples:
    >>> main.__name__
    'main'
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SEVN_ROOT = Path("src/sevn")


def _git_lines(args: list[str]) -> list[str]:
    """Return non-empty lines from a git command (empty when git fails).

    Args:
        args (list[str]): Arguments after ``git``.

    Returns:
        list[str]: Trimmed stdout lines.

    Examples:
        >>> isinstance(_git_lines(["--version"]), list)
        True
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _untracked_sevn_excludes() -> list[str]:
    """Regex excludes for untracked ``src/sevn`` packages that contain ``.py`` files.

    Returns:
        list[str]: Mypy ``--exclude`` regex fragments.

    Examples:
        >>> isinstance(_untracked_sevn_excludes(), list)
        True
    """
    paths = _git_lines(["ls-files", "--others", "--exclude-standard", "src/sevn"])
    package_dirs: set[Path] = set()
    for rel in paths:
        if not rel.endswith(".py"):
            continue
        path = Path(rel)
        if len(path.parts) < 3 or path.parts[0] != "src" or path.parts[1] != "sevn":
            continue
        package_dirs.add(Path("src", "sevn", path.parts[2]))
    return [f"^{re.escape(str(d))}/" for d in sorted(package_dirs)]


def main() -> int:
    """Run ``mypy src/sevn``, skipping untracked packages under ``src/sevn``.

    Returns:
        int: Subprocess exit code.

    Examples:
        >>> isinstance(main(), int)
        True
    """
    cmd = ["uv", "run", "mypy", "src/sevn"]
    excludes = _untracked_sevn_excludes()
    if excludes:
        cmd.extend(["--exclude", "|".join(excludes)])
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False)
    return int(proc.returncode)


if __name__ == "__main__":
    sys.exit(main())
