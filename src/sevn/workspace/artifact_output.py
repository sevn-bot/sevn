"""Artifact output directory confinement for tools and skills.

Module: sevn.workspace.artifact_output
Depends: os, pathlib, sevn.config.defaults

Exports:
    artifact_output_prefix — resolve effective ``out/<session>/`` prefix from config.
    artifact_output_prefix_from_env — read ``SEVN_ARTIFACT_OUTPUT_PREFIX`` for skill scripts.
    is_protected_structured_root_path — whether a root basename is reserved for dedicated tools.
    normalise_output_dir_rel — sanitise configured output-dir segment.
    path_is_under_output_prefix — prefix containment check on POSIX relative paths.
    rebase_artifact_relative_path — rebase bare relative paths under the output prefix.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from sevn.config.defaults import DEFAULT_WORKSPACE_OUTPUT_DIR

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

_ENV_ARTIFACT_OUTPUT_PREFIX = "SEVN_ARTIFACT_OUTPUT_PREFIX"

_PROTECTED_STRUCTURED_ROOT_FILES: frozenset[str] = frozenset(
    {"USER.md", "SOUL.md", "IDENTITY.md", "MEMORY.md", "sevn.json"},
)


def normalise_output_dir_rel(raw: str | None) -> str:
    """Return a sanitised workspace-relative output directory segment.

    Args:
        raw (str | None): Configured ``workspace.output_dir`` value.

    Returns:
        str: Normalised relative path without leading or trailing slashes.

    Raises:
        ValueError: When the path is empty, absolute, or contains ``..``.

    Examples:
        >>> normalise_output_dir_rel("out/")
        'out'
        >>> normalise_output_dir_rel(None)
        'out'
    """
    text = (raw or DEFAULT_WORKSPACE_OUTPUT_DIR).strip().replace("\\", "/").strip("/")
    if not text:
        msg = "workspace.output_dir must be non-empty"
        raise ValueError(msg)
    if text.startswith("/") or Path(text).is_absolute():
        msg = "workspace.output_dir must be relative to the workspace root"
        raise ValueError(msg)
    if ".." in text.split("/"):
        msg = "workspace.output_dir must not contain parent segments"
        raise ValueError(msg)
    return text


def _safe_session_segment(session_id: str) -> str:
    """Return a filesystem-safe session id segment for per-session subfolders.

    Args:
        session_id (str): Gateway session id.

    Returns:
        str: Sanitised single path segment.

    Examples:
        >>> _safe_session_segment("web:abc/def")
        'web_abc_def'
    """
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", session_id.strip())
    return cleaned or "session"


def artifact_output_prefix(
    cfg: WorkspaceConfig | None,
    session_id: str,
) -> str:
    """Resolve the workspace-relative artifact output prefix for a session.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config.
        session_id (str): Active gateway session id.

    Returns:
        str: Prefix such as ``out/<session_id>`` or flat ``out``.

    Examples:
        >>> artifact_output_prefix(None, "sess-1")
        'out/sess-1'
    """
    base = normalise_output_dir_rel(DEFAULT_WORKSPACE_OUTPUT_DIR)
    per_session = True
    if cfg is not None and cfg.workspace is not None:
        base = normalise_output_dir_rel(cfg.workspace.output_dir)
        per_session = bool(cfg.workspace.per_session)
    if per_session and session_id.strip():
        return f"{base}/{_safe_session_segment(session_id)}"
    return base


def artifact_output_prefix_from_env() -> str | None:
    """Read the artifact output prefix injected by the skill runner.

    Returns:
        str | None: Prefix when ``SEVN_ARTIFACT_OUTPUT_PREFIX`` is set, else ``None``.

    Examples:
        >>> artifact_output_prefix_from_env() is None
        True
    """
    raw = os.environ.get(_ENV_ARTIFACT_OUTPUT_PREFIX, "").strip()
    return raw or None


def is_protected_structured_root_path(rel_path: str) -> bool:
    """Return whether ``rel_path`` targets a reserved root bootstrap/config file.

    General-purpose ``write`` / ``create_folder`` / move-copy destinations must not
    touch these paths; use ``write_workspace_md`` for bootstrap markdown instead.

    Args:
        rel_path (str): Workspace-relative path from a tool argument.

    Returns:
        bool: ``True`` for root-level ``USER.md``, ``SOUL.md``, ``sevn.json``, etc.

    Examples:
        >>> is_protected_structured_root_path("SOUL.md")
        True
        >>> is_protected_structured_root_path("memory/2026-06-05.md")
        False
        >>> is_protected_structured_root_path("report.pdf")
        False
    """
    text = rel_path.strip().replace("\\", "/").lstrip("/")
    if not text or "/" in text:
        return False
    return text in _PROTECTED_STRUCTURED_ROOT_FILES


def path_is_under_output_prefix(rel_path: str, output_prefix: str) -> bool:
    """Return whether ``rel_path`` is already under ``output_prefix``.

    Args:
        rel_path (str): Workspace-relative path.
        output_prefix (str): Configured artifact prefix (e.g. ``out/sess``).

    Returns:
        bool: ``True`` when ``rel_path`` equals or nests under the prefix.

    Examples:
        >>> path_is_under_output_prefix("out/sess/page.pdf", "out/sess")
        True
        >>> path_is_under_output_prefix("page.pdf", "out/sess")
        False
    """
    norm = rel_path.strip().replace("\\", "/").strip("/")
    pref = output_prefix.strip().replace("\\", "/").strip("/")
    if not norm or not pref:
        return False
    return norm == pref or norm.startswith(f"{pref}/")


def rebase_artifact_relative_path(raw: str, output_prefix: str) -> str:
    """Rebase a relative artifact path under ``output_prefix``.

    Absolute paths and ``..`` traversal are rejected. Paths already under the
    prefix are returned unchanged.

    Args:
        raw (str): Tool- or skill-supplied relative path.
        output_prefix (str): Session output prefix under the workspace root.

    Returns:
        str: Workspace-relative POSIX path confined under ``output_prefix``.

    Raises:
        ValueError: When ``raw`` is absolute or traverses above the workspace.

    Examples:
        >>> rebase_artifact_relative_path("page.md", "out/sess")
        'out/sess/page.md'
        >>> rebase_artifact_relative_path("out/sess/a.pdf", "out/sess")
        'out/sess/a.pdf'
    """
    text = raw.strip().replace("\\", "/")
    if not text:
        msg = "artifact path must be non-empty"
        raise ValueError(msg)
    if text.startswith("/"):
        msg = f"artifact path {raw!r} must be workspace-relative, not absolute"
        raise ValueError(msg)
    candidate = Path(text).expanduser()
    if candidate.is_absolute():
        msg = f"artifact path {raw!r} must be workspace-relative, not absolute"
        raise ValueError(msg)
    normalised = os.path.normpath(text).replace("\\", "/")
    if (
        normalised == os.pardir
        or normalised.startswith(os.pardir + "/")
        or os.path.isabs(normalised)
    ):
        msg = f"artifact path {raw!r} escapes workspace root"
        raise ValueError(msg)
    rel = normalised.lstrip("/")
    if path_is_under_output_prefix(rel, output_prefix):
        return rel
    prefix = output_prefix.strip("/")
    base_dir = prefix.split("/")[0] if prefix else DEFAULT_WORKSPACE_OUTPUT_DIR
    if rel == base_dir or rel.startswith(f"{base_dir}/"):
        rest = rel[len(base_dir) :].lstrip("/")
        return f"{prefix}/{rest}" if rest else prefix
    return f"{prefix}/{rel}" if rel else prefix


__all__ = [
    "artifact_output_prefix",
    "artifact_output_prefix_from_env",
    "is_protected_structured_root_path",
    "normalise_output_dir_rel",
    "path_is_under_output_prefix",
    "rebase_artifact_relative_path",
]
