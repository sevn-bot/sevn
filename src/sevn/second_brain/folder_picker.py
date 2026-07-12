"""Workspace-relative folder browser helpers for Second Brain vault pickers.

Module: sevn.second_brain.folder_picker
Depends: pathlib, sevn.tools.paths

Exports:
    list_workspace_subdirs — immediate child directories under a browse path.
    normalise_browse_path — sanitise a workspace-relative browse cursor.

Examples:
    >>> import tempfile
    >>> from pathlib import Path
    >>> with tempfile.TemporaryDirectory() as td:
    ...     ws = Path(td)
    ...     _ = (ws / "obsidian").mkdir()
    ...     rows = list_workspace_subdirs(ws, ".")
    ...     rows[0]["name"]
    'obsidian'
"""

from __future__ import annotations

from pathlib import Path

from sevn.tools.paths import WorkspacePathError, resolve_workspace_relative_path


def normalise_browse_path(raw: str) -> str:
    """Return a safe workspace-relative browse path (``"."`` for workspace root).

    Args:
        raw (str): Operator browse cursor.

    Returns:
        str: Normalised POSIX path relative to workspace root.

    Raises:
        WorkspacePathError: When the path escapes the workspace or uses ``..``.

    Examples:
        >>> normalise_browse_path(".")
        '.'
        >>> normalise_browse_path("obsidian/alex_AI")
        'obsidian/alex_AI'
    """
    text = raw.strip().replace("\\", "/").lstrip("/")
    if not text or text == ".":
        return "."
    parts = [p for p in text.split("/") if p and p != "."]
    if ".." in parts:
        msg = "browse path must not contain '..' components"
        raise WorkspacePathError(msg)
    return "/".join(parts)


def list_workspace_subdirs(
    content_root: Path,
    browse_path: str,
    *,
    max_entries: int = 8,
) -> list[dict[str, str]]:
    """List immediate subdirectories under *browse_path* within *content_root*.

    Args:
        content_root (Path): Workspace content root.
        browse_path (str): Current browse cursor (``"."`` = workspace root).
        max_entries (int): Maximum directories returned (default ``8``).

    Returns:
        list[dict[str, str]]: Rows with ``name`` and ``relative`` POSIX paths.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     ws = Path(td)
        ...     _ = (ws / "obsidian").mkdir()
        ...     out = list_workspace_subdirs(ws, ".")
        ...     out[0]["relative"]
        'obsidian'
    """
    rel = normalise_browse_path(browse_path)
    base = (
        content_root.expanduser().resolve()
        if rel == "."
        else resolve_workspace_relative_path(content_root, rel)
    )
    if not base.is_dir():
        return []
    rows: list[dict[str, str]] = []
    for child in sorted(base.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        child_rel = child.name if rel == "." else f"{rel}/{child.name}"
        rows.append({"name": child.name, "relative": child_rel.replace("\\", "/")})
        if len(rows) >= max_entries:
            break
    return rows


__all__ = ["list_workspace_subdirs", "normalise_browse_path"]
