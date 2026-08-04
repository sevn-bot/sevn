#!/usr/bin/env python3
"""Refuse commits from the primary checkout unless explicitly overridden.

Module: scripts.check_primary_checkout_commit
Depends: os, pathlib, subprocess, sys

Exports:
    is_linked_worktree — True when cwd is a linked git worktree.
    main — exit 1 on primary checkout without ``SEVN_ALLOW_PRIMARY_COMMIT=1``.

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
_OVERRIDE_ENV = "SEVN_ALLOW_PRIMARY_COMMIT"


def _repo_root(cwd: Path | None = None) -> Path:
    """Return git toplevel for ``cwd`` (or process cwd).

    Args:
        cwd (Path | None): Starting directory; defaults to ``Path.cwd()``.

    Returns:
        Path: Repository root.

    Examples:
        >>> _repo_root(REPO).is_dir()
        True
    """
    start = cwd or Path.cwd()
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
        cwd=start,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "git rev-parse --show-toplevel failed").strip()
        raise RuntimeError(msg)
    return Path(proc.stdout.strip())


def _git_path(*args: str, cwd: Path) -> str:
    """Run ``git rev-parse`` and return stdout stripped.

    Args:
        args (str): Extra ``rev-parse`` arguments (e.g. ``--git-dir``).
        cwd (Path): Working directory for the subprocess.

    Returns:
        str: Absolute path from git.

    Examples:
        >>> _git_path("--git-common-dir", cwd=REPO)  # doctest: +SKIP
        '/path/to/.git'
    """
    proc = subprocess.run(
        ["git", "rev-parse", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "git rev-parse failed").strip()
        raise RuntimeError(msg)
    return proc.stdout.strip()


def is_linked_worktree(cwd: Path | None = None) -> bool:
    """Return whether ``cwd`` is a linked worktree (not the primary checkout).

    Linked worktrees have ``--git-dir`` != ``--git-common-dir`` (absolute paths).

    Args:
        cwd (Path | None): Repo root or worktree root; defaults to ``REPO``.

    Returns:
        bool: ``True`` for linked worktrees.

    Examples:
        >>> isinstance(is_linked_worktree(REPO), bool)
        True
    """
    root = cwd or REPO
    git_dir = _git_path("--path-format=absolute", "--git-dir", cwd=root)
    common = _git_path("--path-format=absolute", "--git-common-dir", cwd=root)
    return git_dir != common


def main() -> int:
    """Block commits on the primary checkout unless override env is set.

    Returns:
        int: ``0`` when commit is allowed; ``1`` when blocked.

    Examples:
        >>> main() in (0, 1)
        True
    """
    if os.environ.get(_OVERRIDE_ENV) == "1":
        return 0
    try:
        linked = is_linked_worktree(_repo_root())
    except RuntimeError as exc:
        print(f"check-primary-checkout-commit: FAIL — {exc}", file=sys.stderr)
        return 1
    if linked:
        return 0

    print(
        "check-primary-checkout-commit: BLOCKED — commits from the primary checkout "
        "are not allowed (D1: primary checkout is fetch/status/docs only).\n"
        "\n"
        "Do wave implementation in a linked worktree, then commit and push from there:\n"
        "  git worktree add ../sevn-<topic> -b feature/<topic> origin/pre-0.0.1\n"
        "  cd ../sevn-<topic> && … edit … && git commit && git push\n"
        "\n"
        f"Emergency override (discouraged): {_OVERRIDE_ENV}=1 git commit …",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
