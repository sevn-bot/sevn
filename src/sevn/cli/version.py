"""Resolve CLI version strings for ``sevn --version`` / ``sevn version`` (#123 / D8).

Module: sevn.cli.version
Depends: importlib.metadata (stdlib), pathlib (stdlib), subprocess (stdlib)

Exports:
    resolve_cli_version_string — git ``<branch>-<commit8>`` when available, else package semver.
"""

from __future__ import annotations

import subprocess  # nosec B404 — fixed git argv only; no shell
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path

from sevn.cli.repo_sync import RepoSyncError, resolve_sevn_repo_root

_PACKAGE_NAME = "sevn"


def _run_git(args: list[str], repo_root: Path) -> str | None:
    """Return trimmed stdout of ``git *args`` in *repo_root*, or ``None`` on failure.

    Args:
        args (list[str]): Git subcommand argv after ``git`` (fixed, no shell).
        repo_root (Path): Directory used as the git working tree.

    Returns:
        str | None: Trimmed stdout when git exits ``0`` with output, else ``None``.

    Examples:
        >>> from pathlib import Path
        >>> _run_git(["rev-parse", "HEAD"], Path("/nonexistent-path-for-doctest")) is None
        True
    """
    try:
        out = subprocess.run(  # nosec B603 B607
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode == 0 and out.stdout.strip():
        return out.stdout.strip()
    return None


def _git_branch_commit_version(repo_root: Path) -> str | None:
    """Return ``<branch>-<commit8>`` for *repo_root*, or ``None`` when git is unavailable.

    Args:
        repo_root (Path): Git working tree root.

    Returns:
        str | None: Branch-commit string, e.g. ``wave/issues-aug-a-defects-169a7002``.

    Examples:
        >>> from pathlib import Path
        >>> _git_branch_commit_version(Path("/nonexistent-path-for-doctest")) is None
        True
    """
    short_sha = _run_git(["rev-parse", "--short=8", "HEAD"], repo_root)
    if not short_sha:
        return None
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root)
    if not branch:
        return None
    return f"{branch}-{short_sha}"


def _git_version_from_candidates(*candidates: Path | None) -> str | None:
    """Return the first successful ``<branch>-<commit8>`` among *candidates*.

    Args:
        candidates (Path | None): Git roots to probe in order.

    Returns:
        str | None: First branch-commit string, or ``None`` when all probes fail.

    Examples:
        >>> _git_version_from_candidates(None) is None
        True
    """
    for candidate in candidates:
        if candidate is None:
            continue
        git_version = _git_branch_commit_version(candidate)
        if git_version is not None:
            return git_version
    return None


def _discover_from_cwd() -> Path | None:
    """Return the sevn checkout from cwd/env/workspace heuristics.

    Returns:
        Path | None: Resolved checkout root, or ``None`` when lookup fails.

    Examples:
        >>> isinstance(_discover_from_cwd(), (type(None), Path))
        True
    """
    try:
        return resolve_sevn_repo_root()
    except RepoSyncError:
        return None


def _discover_from_installed_package() -> Path | None:
    """Return the checkout containing this module (editable installs / isolated test cwd).

    Returns:
        Path | None: Resolved checkout root, or ``None`` when lookup fails.

    Examples:
        >>> isinstance(_discover_from_installed_package(), (type(None), Path))
        True
    """
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        try:
            return resolve_sevn_repo_root(candidate)
        except RepoSyncError:
            continue
    return None


def _package_version() -> str:
    """Return the installed ``sevn`` package semver, or a safe placeholder.

    Returns:
        str: Package version from metadata, or ``"0.0.0"`` when not installed.

    Examples:
        >>> isinstance(_package_version(), str)
        True
    """
    try:
        return pkg_version(_PACKAGE_NAME)
    except PackageNotFoundError:
        return "0.0.0"


def resolve_cli_version_string(*, repo_root: Path | None = None) -> str:
    """Resolve the operator-facing CLI version string (D8).

    Prefers ``<branch>-<commit8>`` from git when metadata is available inside a
    checkout; falls back to :func:`importlib.metadata.version` for installed wheels.

    Args:
        repo_root (Path | None, optional): Git working tree. When ``None``, discovery
            walks the installed package checkout first, then cwd/env/workspace heuristics.

    Returns:
        str: Branch-commit identity or package semver.

    Examples:
        >>> isinstance(resolve_cli_version_string(), str)
        True
    """
    if repo_root is not None:
        git_version = _git_branch_commit_version(repo_root.expanduser().resolve())
        if git_version is not None:
            return git_version
        return _package_version()

    git_version = _git_version_from_candidates(
        _discover_from_installed_package(),
        _discover_from_cwd(),
    )
    if git_version is not None:
        return git_version
    return _package_version()


__all__ = ["resolve_cli_version_string"]
