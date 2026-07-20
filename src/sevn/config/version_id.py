"""Resolve and persist build ``version_id`` in ``sevn.json`` (issue #30 / plan D2).

Module: sevn.config.version_id
Depends: importlib.metadata (stdlib), json (stdlib), os (stdlib), pathlib (stdlib),
    subprocess (stdlib)

Exports:
    resolve_version_id — env > git short SHA > package version > ``unknown``.
    ensure_version_id — resolve then persist into top-level ``version_id`` when needed.

Examples:
    >>> from pathlib import Path
    >>> from sevn.config.version_id import resolve_version_id
    >>> isinstance(resolve_version_id(repo_root=Path(".")), str)
    True
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess  # nosec B404 — fixed git argv only; no shell
from importlib.metadata import PackageNotFoundError
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

_PACKAGE_NAME = "sevn"


def _resolve_git_short_head(repo_root: Path) -> str:
    """Return ``git rev-parse --short HEAD`` for *repo_root*, or ``unknown``.

    Mirrors the probe style in :func:`sevn.agent.context_manifest._resolve_git_commit`
    without importing agent-context code.

    Args:
        repo_root (Path): Directory passed as ``git`` working tree (typically a checkout).

    Returns:
        str: Short commit hash, or ``"unknown"`` when git is unavailable.

    Examples:
        >>> from pathlib import Path
        >>> _resolve_git_short_head(Path("/nonexistent-path-for-doctest"))
        'unknown'
    """
    try:
        out = subprocess.run(  # nosec B603 B607
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def resolve_version_id(*, repo_root: Path | None = None) -> str:
    """Resolve the running bot build identity (D2).

    Resolution order:

    1. Non-empty ``SEVN_VERSION_ID`` environment variable.
    2. ``git rev-parse --short HEAD`` from *repo_root* when git succeeds.
    3. ``importlib.metadata.version("sevn")``.
    4. ``"unknown"``.

    Args:
        repo_root (Path | None, optional): Git working tree for step (2). When
            ``None``, step (2) is skipped.

    Returns:
        str: Resolved build identity string.

    Examples:
        >>> resolve_version_id(repo_root=None)  # doctest: +SKIP
        'abc1234'
    """
    env_val = os.environ.get("SEVN_VERSION_ID", "")
    if env_val.strip():
        return env_val.strip()

    if repo_root is not None:
        git_sha = _resolve_git_short_head(repo_root.expanduser().resolve())
        if git_sha != "unknown":
            return git_sha

    try:
        return importlib.metadata.version(_PACKAGE_NAME)
    except PackageNotFoundError:
        pass

    return "unknown"


def _load_sevn_doc(sevn_json_path: Path) -> dict[str, Any]:
    """Load and validate the root object from ``sevn.json``.

    Args:
        sevn_json_path (Path): Path to the workspace config file.

    Returns:
        dict[str, Any]: Parsed workspace document.

    Raises:
        ValueError: When the JSON root is not an object.

    Examples:
        >>> import json, tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> sj = td / "sevn.json"
        >>> _ = sj.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        >>> _load_sevn_doc(sj)["schema_version"]
        1
    """
    raw = sevn_json_path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        msg = "sevn.json root must be an object"
        raise ValueError(msg)
    return parsed


def _stored_version_id(doc: dict[str, Any]) -> str | None:
    """Return the stored top-level ``version_id`` when present and non-empty.

    Args:
        doc (dict[str, Any]): Parsed ``sevn.json`` document.

    Returns:
        str | None: Trimmed stored value, or ``None`` when absent/blank.

    Examples:
        >>> _stored_version_id({"version_id": " build-1 "})
        'build-1'
        >>> _stored_version_id({}) is None
        True
    """
    existing = doc.get("version_id")
    if isinstance(existing, str) and existing.strip():
        return existing.strip()
    return None


def _persist_decision(stored: str | None, resolved: str) -> tuple[str, bool]:
    """Decide the effective value and whether ``sevn.json`` should be rewritten.

    Args:
        stored (str | None): Existing persisted ``version_id``, if any.
        resolved (str): Freshly resolved build identity.

    Returns:
        tuple[str, bool]: ``(effective_value, should_write)`` per plan D2.

    Examples:
        >>> _persist_decision(None, "abc1234")
        ('abc1234', True)
        >>> _persist_decision("kept", "unknown")
        ('kept', False)
    """
    if stored is None:
        return resolved, True
    if resolved == "unknown":
        return stored, False
    if resolved != stored:
        return resolved, True
    return stored, False


def ensure_version_id(
    sevn_json_path: Path,
    *,
    repo_root: Path | None = None,
) -> str:
    """Resolve ``version_id`` and persist into ``sevn.json`` when appropriate (D2).

    Writes the top-level ``"version_id"`` key when it is missing, or when boot
    resolves a different non-``unknown`` value. Does not replace an existing
    stored value when resolution falls back to ``unknown`` (no thrashing).

    Args:
        sevn_json_path (Path): Path to the workspace ``sevn.json`` file.
        repo_root (Path | None, optional): Git working tree for resolution; defaults
            to ``sevn_json_path`` parent when omitted.

    Returns:
        str: Effective ``version_id`` after any persist (stored or newly written).

    Examples:
        >>> import os, tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> sj = td / "sevn.json"
        >>> _ = sj.write_text(
        ...     '{"schema_version": 1, "workspace_root": "."}',
        ...     encoding="utf-8",
        ... )
        >>> os.environ["SEVN_VERSION_ID"] = "doctest-build"
        >>> ensure_version_id(sj, repo_root=td)  # doctest: +SKIP
        'doctest-build'
    """
    path = sevn_json_path.expanduser().resolve()
    git_root = path.parent if repo_root is None else repo_root.expanduser().resolve()
    resolved = resolve_version_id(repo_root=git_root)
    doc = _load_sevn_doc(path)
    stored = _stored_version_id(doc)
    effective, should_write = _persist_decision(stored, resolved)
    if not should_write:
        return effective
    doc["version_id"] = effective
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return effective


__all__ = ["ensure_version_id", "resolve_version_id"]
