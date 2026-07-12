"""Path helpers rejecting ``.llmignore/`` realpaths (`specs/11-tools-registry.md` §4.3).

Module: sevn.tools.paths
Depends: sevn.security.llmignore

Exports:
    ensure_path_not_under_llmignore — raise when a candidate path is blocked.
    display_path_for_tool — agent-facing workspace-relative path string.
    rebase_checkout_absolute_path — map an absolute checkout path onto source_code/.
    resolve_workspace_relative_path — resolve a workspace-relative path with containment.
    resolve_artifact_tool_path — resolve mutating-tool paths under the artifact output dir.
    resolve_tool_path — resolve a workspace-relative path for file tools.
    filter_visible_entries — drop ``.llmignore`` subtree names from directory listings.
    WorkspacePathError — raised when a path escapes the workspace root.

Examples:
    >>> from pathlib import Path
    >>> ws = Path("/tmp/ws")
    >>> p = ws / ".llmignore" / "blocked" / "x.txt"
    >>> import pytest
    >>> with pytest.raises(PermissionError):
    ...     ensure_path_not_under_llmignore(p, ws)
"""

from __future__ import annotations

from pathlib import Path

from sevn.security.llmignore import is_llmignored
from sevn.workspace.artifact_output import (
    is_protected_structured_root_path,
    rebase_artifact_relative_path,
)


class WorkspacePathError(ValueError):
    """Raised when a tool-supplied path fails workspace containment rules."""


def ensure_path_not_under_llmignore(candidate: Path, workspace: Path) -> Path:
    """Resolve ``candidate`` and refuse paths that live under ``workspace/.llmignore/``.

    Args:
        candidate (Path): Filesystem path supplied by a tool or test double.
        workspace (Path): Workspace content root.

    Returns:
        Path: Resolved absolute path when allowed.

    Raises:
        PermissionError: When ``is_llmignored`` flags the path.

    Examples:
        >>> from pathlib import Path
        >>> ws = Path("/tmp/ws")
        >>> allowed = ws / "readme.md"
        >>> # does not raise when not under .llmignore
        >>> isinstance(ensure_path_not_under_llmignore(allowed, ws), Path)
        True
    """
    if is_llmignored(candidate, workspace):
        msg = "Path rejected: under workspace .llmignore/ subtree"
        raise PermissionError(msg)
    return candidate.expanduser().resolve()


def rebase_checkout_absolute_path(raw: str, checkout: Path | None) -> str | None:
    """Map an absolute path under the sevn checkout onto the ``source_code/`` mirror.

    Tier-B models (notably MiniMax-M3) often echo the *absolute* checkout path from the
    transcript — e.g. ``/Users/.../sevn.bot/src/sevn/gateway/agent_turn.py`` — instead of
    the prompt-mandated workspace-relative ``source_code/…`` path. The file-tool sandbox
    is jailed to the workspace root, so such paths are rejected as ``escapes workspace
    root``. When the path is absolute and lives under ``checkout``, this returns the
    equivalent ``source_code/<relative>`` path so the first tool call succeeds; otherwise
    ``None`` (caller keeps the original path unchanged).

    Args:
        raw (str): Raw path supplied by the model/tool call.
        checkout (Path | None): Resolved sevn checkout root, or ``None`` to disable.

    Returns:
        str | None: ``source_code/<rel>`` (or bare ``source_code``) when ``raw`` is an
            absolute path under ``checkout``; otherwise ``None``.

    Examples:
        >>> from pathlib import Path
        >>> rebase_checkout_absolute_path("/repo/src/x.py", Path("/repo"))
        'source_code/src/x.py'
        >>> rebase_checkout_absolute_path("/repo", Path("/repo"))
        'source_code'
        >>> rebase_checkout_absolute_path("src/x.py", Path("/repo")) is None
        True
        >>> rebase_checkout_absolute_path("/elsewhere/x.py", Path("/repo")) is None
        True
        >>> rebase_checkout_absolute_path("/repo/x.py", None) is None
        True
    """
    if checkout is None:
        return None
    text = raw.strip().replace("\\", "/")
    if not text.startswith("/"):
        return None
    try:
        candidate = Path(text).expanduser().resolve()
        checkout_root = checkout.expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    try:
        rel = candidate.relative_to(checkout_root)
    except ValueError:
        return None
    rel_posix = rel.as_posix()
    return "source_code" if rel_posix in ("", ".") else f"source_code/{rel_posix}"


def resolve_workspace_relative_path(
    workspace: Path,
    rel_path: str,
    *,
    checkout: Path | None = None,
) -> Path:
    """Resolve ``rel_path`` under ``workspace`` with containment and ``.llmignore`` guard.

    Args:
        workspace (Path): Workspace content root.
        rel_path (str): Path relative to the workspace root (POSIX separators).
        checkout (Path | None, optional): Sevn checkout root. When set, an absolute path
            under it is rebased onto ``source_code/<rel>`` before containment (see
            :func:`rebase_checkout_absolute_path`). Defaults to ``None`` (no rewrite).

    Returns:
        Path: Resolved absolute path when allowed.

    Raises:
        WorkspacePathError: When the path is empty, traverses ``..``, or escapes the root.
        PermissionError: When the resolved path is under ``workspace/.llmignore/``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> _ = (ws / "notes.md").write_text("hi", encoding="utf-8")
        >>> out = resolve_workspace_relative_path(ws, "notes.md")
        >>> out.name
        'notes.md'
    """
    rebased = rebase_checkout_absolute_path(rel_path, checkout)
    if rebased is not None:
        rel_path = rebased
    text = rel_path.strip().replace("\\", "/")
    if not text:
        msg = "path must be non-empty"
        raise WorkspacePathError(msg)
    if text.startswith("/"):
        candidate = Path(text).expanduser().resolve()
    else:
        normalised = text.lstrip("/")
        parts = normalised.split("/")
        if ".." in parts:
            msg = "path must not contain '..' components"
            raise WorkspacePathError(msg)
        candidate = (workspace / normalised).resolve()
    root = workspace.expanduser().resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        msg = f"path {rel_path!r} escapes workspace root"
        raise WorkspacePathError(msg) from exc
    return ensure_path_not_under_llmignore(candidate, workspace)


def resolve_artifact_tool_path(
    workspace: Path,
    rel_path: str,
    *,
    output_prefix: str,
    allow_existing_outside: bool = False,
) -> tuple[Path, str]:
    """Resolve a mutating-tool path with artifact output-dir confinement.

    Root bootstrap/config basenames (``USER.md``, ``SOUL.md``, ``sevn.json``) are
    rejected for new writes — use ``write_workspace_md`` instead. When
    ``allow_existing_outside`` is true and the literal path already exists, edits
    keep the existing location instead of rebasing.

    Args:
        workspace (Path): Workspace content root.
        rel_path (str): Path relative to the workspace root.
        output_prefix (str): Session artifact prefix (e.g. ``out/<session_id>``).
        allow_existing_outside (bool, optional): Permit editing an existing file
            outside the output dir. Defaults to ``False``.

    Returns:
        tuple[Path, str]: ``(absolute_path, display_path)`` for agent envelopes.

    Raises:
        WorkspacePathError: When the path is invalid or escapes the workspace root.
        PermissionError: When the resolved path is under ``.llmignore/``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> abs_p, disp = resolve_artifact_tool_path(
        ...     ws, "page.md", output_prefix="out/sess",
        ... )
        >>> disp
        'out/sess/page.md'
    """
    text = rel_path.strip()
    if is_protected_structured_root_path(text):
        if allow_existing_outside:
            try:
                existing = resolve_workspace_relative_path(workspace, text)
            except WorkspacePathError:
                existing = None
            if existing is not None and existing.exists():
                return resolve_tool_path(workspace, text)
        msg = (
            f"path {rel_path!r} is reserved for write_workspace_md "
            "(USER.md, SOUL.md, IDENTITY.md, MEMORY.md) or config tooling"
        )
        raise WorkspacePathError(msg)
    if allow_existing_outside:
        try:
            existing = resolve_workspace_relative_path(workspace, text)
        except WorkspacePathError:
            existing = None
        if existing is not None and existing.exists():
            return resolve_tool_path(workspace, text)
    try:
        rebased = rebase_artifact_relative_path(text, output_prefix)
    except ValueError as exc:
        raise WorkspacePathError(str(exc)) from exc
    return resolve_tool_path(workspace, rebased)


def resolve_tool_path(
    workspace: Path,
    rel_path: str,
    *,
    checkout: Path | None = None,
) -> tuple[Path, str]:
    """Resolve a workspace-relative path for tier-B file tools.

    Source code lives in the workspace at ``source_code/`` (a read-only full-repo
    mirror), so checkout files resolve through the same workspace-relative path
    handling as any other file (e.g. ``source_code/sevn/gateway/agent_turn.py``).

    Args:
        workspace (Path): Workspace content root.
        rel_path (str): Path relative to the workspace root.
        checkout (Path | None, optional): Sevn checkout root. When set, an absolute path
            under it is rebased onto ``source_code/<rel>`` before containment. Defaults to
            ``None`` (no rewrite).

    Returns:
        tuple[Path, str]: ``(absolute_path, display_path)`` where ``display_path`` is
            the workspace-relative POSIX path for agent-facing envelopes.

    Raises:
        WorkspacePathError: When the path is invalid or escapes the workspace root.
        PermissionError: When the resolved path is under ``.llmignore/``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> _ = (ws / "notes.md").write_text("hi", encoding="utf-8")
        >>> abs_p, disp = resolve_tool_path(ws, "notes.md")
        >>> disp
        'notes.md'
    """
    absolute = resolve_workspace_relative_path(workspace, rel_path, checkout=checkout)
    rel_display = absolute.relative_to(workspace.expanduser().resolve()).as_posix()
    return absolute, rel_display


def display_path_for_tool(workspace: Path, absolute: Path) -> str:
    """Return agent-facing workspace-relative path string for a resolved path.

    Args:
        workspace (Path): Workspace content root.
        absolute (Path): Resolved filesystem path.

    Returns:
        str: Workspace-relative POSIX path.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> f = ws / "a.txt"
        >>> _ = f.write_text("x", encoding="utf-8")
        >>> display_path_for_tool(ws, f.resolve())
        'a.txt'
    """
    resolved = absolute.expanduser().resolve()
    return resolved.relative_to(workspace.expanduser().resolve()).as_posix()


def filter_visible_entries(workspace: Path, directory: Path) -> list[Path]:
    """Return child paths under ``directory`` omitting ``.llmignore`` subtree entries.

    Args:
        workspace (Path): Workspace content root for ``is_llmignored`` checks.
        directory (Path): Resolved directory to list.

    Returns:
        list[Path]: Visible children sorted by name (directories before files).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> d = ws / "pkg"
        >>> _ = d.mkdir()
        >>> _ = (d / "a.txt").write_text("x", encoding="utf-8")
        >>> names = [p.name for p in filter_visible_entries(ws, d.resolve())]
        >>> names
        ['a.txt']
    """
    if not directory.is_dir():
        return []
    visible = [child for child in directory.iterdir() if not is_llmignored(child, workspace)]
    visible.sort(key=lambda item: (not item.is_dir(), item.name.lower()))
    return visible


__all__ = [
    "WorkspacePathError",
    "display_path_for_tool",
    "ensure_path_not_under_llmignore",
    "filter_visible_entries",
    "rebase_checkout_absolute_path",
    "resolve_artifact_tool_path",
    "resolve_tool_path",
    "resolve_workspace_relative_path",
]
