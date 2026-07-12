"""Directory listing, glob, find, and metadata tools (`specs/11-tools-registry.md` §4.3).

Module: sevn.tools.file_ops.list_glob
Depends: sevn.tools.base, sevn.tools.context, sevn.tools.decorator, sevn.tools.paths

Exports:
    list_dir_tool — list directory entries with metadata.
    glob_tool — glob files under a workspace directory.
    find_file_tool — find files by filename fragment.
    file_info_tool — stat metadata for one path.
"""

from __future__ import annotations

import json
import stat
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from sevn.security.llmignore import is_llmignored
from sevn.tools.base import enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool
from sevn.tools.file_ops.graphify_result_prefix import graphify_prefix_for_search_path
from sevn.tools.paths import (
    WorkspacePathError,
    display_path_for_tool,
    filter_visible_entries,
    resolve_tool_path,
)

MAX_LISTING_RESULTS: Final[int] = 1000


def _path_error_envelope(exc: BaseException) -> str:
    """Map guard failures to §3.1 envelopes.

    Args:
        exc (BaseException): Raised guard or validation error.

    Returns:
        str: JSON failure envelope string.

    Examples:
        >>> "PERMISSION_DENIED" in _path_error_envelope(PermissionError("blocked"))
        True
    """
    if isinstance(exc, PermissionError):
        return enveloped_failure(str(exc), code=ToolResultCode.PERMISSION_DENIED)
    if isinstance(exc, WorkspacePathError):
        return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)
    return enveloped_failure(str(exc), code=ToolResultCode.INTERNAL_ERROR)


def _entry_metadata(workspace: Path, child: Path) -> dict[str, object]:
    """Build one directory listing row for ``list_dir``.

    Args:
        workspace (Path): Workspace content root.
        child (Path): Resolved child path.

    Returns:
        dict[str, object]: Name, type, size, mtime, and agent-facing path.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> f = ws / "a.txt"
        >>> _ = f.write_text("x", encoding="utf-8")
        >>> row = _entry_metadata(ws, f.resolve())
        >>> row["name"]
        'a.txt'
    """
    rel = display_path_for_tool(workspace, child.resolve())
    try:
        st = child.stat()
    except OSError:
        return {"name": child.name, "path": rel, "type": "unknown"}
    kind = "directory" if child.is_dir() else "file"
    mode = stat.filemode(st.st_mode)
    return {
        "name": child.name,
        "path": rel,
        "type": kind,
        "size": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat(),
        "mode": mode,
    }


def _rel_posix(workspace: Path, path: Path) -> str:
    """Return a workspace-relative POSIX path string.

    Args:
        workspace (Path): Workspace content root.
        path (Path): Resolved absolute path.

    Returns:
        str: Relative POSIX path.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> f = ws / "x.txt"
        >>> _ = f.write_text("", encoding="utf-8")
        >>> _rel_posix(ws, f.resolve())
        'x.txt'
    """
    return path.relative_to(workspace.expanduser().resolve()).as_posix()


@sevn_tool(
    name="list_dir",
    category="file_ops",
    description="List a workspace directory with file metadata.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative directory (default '.').",
            },
            "return_only": {
                "type": "string",
                "enum": ["files", "folders", "all"],
                "description": (
                    "Filter to files only, folders only, or both. Defaults to 'all'. "
                    "Use 'folders' for 'which folders are in X' questions."
                ),
            },
        },
        "required": [],
    },
    large_result=True,
)
async def list_dir_tool(
    ctx: ToolContext,
    path: str = ".",
    return_only: str | None = None,
) -> str:
    """List one directory omitting ``.llmignore`` subtree entries.

    Args:
        ctx (ToolContext): Invocation context.
        path (str): Workspace-relative directory path.
        return_only (str | None): ``"files"``, ``"folders"``, ``"all"``, or ``None``.
            When ``"files"`` or ``"folders"``, the response also includes a flat
            ``names`` list for quick scanning.

    Returns:
        str: §3.1 JSON envelope with ``entries`` metadata rows.

    Examples:
        >>> list_dir_tool.__name__
        'list_dir_tool'
    """
    root = ctx.workspace_path
    try:
        target, rel = resolve_tool_path(root, path, checkout=ctx.checkout_path)
    except (PermissionError, WorkspacePathError) as exc:
        return _path_error_envelope(exc)
    if not target.is_dir():
        return enveloped_failure(f"not a directory: {path}", code=ToolResultCode.VALIDATION_ERROR)
    children = list(filter_visible_entries(root, target))
    all_entries = [_entry_metadata(root, child) for child in children]

    kind_filter: str | None = None
    if return_only in ("files", "folders"):
        kind_filter = "file" if return_only == "files" else "directory"
        all_entries = [e for e in all_entries if e.get("type") == kind_filter]

    total_count = len(all_entries)
    truncated = total_count > MAX_LISTING_RESULTS
    if truncated:
        spill_dir = root / ".sevn" / "tool_results" / ctx.session_id
        spill_dir.mkdir(parents=True, exist_ok=True)
        spill_file = spill_dir / f"list_dir-{uuid.uuid4().hex}.json"
        spill_file.write_text(
            json.dumps(
                {"path": rel, "entries": all_entries}, separators=(",", ":"), ensure_ascii=False
            ),
            encoding="utf-8",
        )
        spill_rel = spill_file.resolve().relative_to(root.resolve()).as_posix()
        summary = {
            "files": sum(1 for e in all_entries if e.get("type") == "file"),
            "folders": sum(1 for e in all_entries if e.get("type") == "directory"),
        }
        return enveloped_success(
            {
                "path": rel,
                "return_only": return_only or "all",
                "count": total_count,
                "shown": MAX_LISTING_RESULTS,
                "truncated": True,
                "summary": summary,
                "spill_path": spill_rel,
                "spill_notice": (
                    f"{total_count} entries total; {MAX_LISTING_RESULTS} capped inline; "
                    f"read the spill file directly at {spill_rel} for the full list"
                ),
            },
        )

    payload: dict[str, object] = {
        "path": rel,
        "return_only": return_only or "all",
        "entries": all_entries,
        "count": total_count,
        "shown": total_count,
        "truncated": False,
    }
    if kind_filter is not None:
        payload["names"] = [str(e.get("name", "")) for e in all_entries]
    return enveloped_success(payload)


@sevn_tool(
    name="glob",
    category="file_ops",
    description="Glob-find files under a workspace directory by pattern.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern (e.g. '**/*.py').",
            },
            "path": {
                "type": "string",
                "description": "Base directory (workspace-relative, default '.').",
            },
        },
        "required": ["pattern"],
    },
    large_result=True,
)
async def glob_tool(ctx: ToolContext, pattern: str, path: str = ".") -> str:
    """Return workspace-relative paths matching ``pattern`` under ``path``.

    Args:
        ctx (ToolContext): Invocation context.
        pattern (str): Glob pattern interpreted by :meth:`pathlib.Path.glob`.
        path (str): Base directory relative to workspace root.

    Returns:
        str: §3.1 JSON envelope with matched ``paths`` (capped).

    Examples:
        >>> glob_tool.__name__
        'glob_tool'
    """
    root = ctx.workspace_path
    pattern_text = pattern.strip()
    if not pattern_text:
        return enveloped_failure("pattern must be non-empty", code=ToolResultCode.VALIDATION_ERROR)
    try:
        base, rel_base = resolve_tool_path(root, path, checkout=ctx.checkout_path)
    except (PermissionError, WorkspacePathError) as exc:
        return _path_error_envelope(exc)
    if not base.is_dir():
        return enveloped_failure(f"not a directory: {path}", code=ToolResultCode.VALIDATION_ERROR)

    matches: list[str] = []
    truncated = False
    try:
        for candidate in sorted(base.glob(pattern_text)):
            if is_llmignored(candidate, root):
                continue
            if not candidate.exists():
                continue
            matches.append(
                display_path_for_tool(root, candidate.resolve()),
            )
            if len(matches) >= MAX_LISTING_RESULTS:
                truncated = True
                break
    except OSError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)

    prefix = graphify_prefix_for_search_path(ctx.graphify_profiles or [], base)
    content = prefix + ("\n".join(matches) if matches else "(no matches)")
    return enveloped_success(
        {
            "pattern": pattern_text,
            "base": rel_base,
            "paths": matches,
            "content": content,
            "count": len(matches),
            "truncated": truncated,
        },
    )


@sevn_tool(
    name="find_file",
    category="file_ops",
    description="Find files by exact or partial filename under a workspace tree.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Filename or substring to match."},
            "path": {
                "type": "string",
                "description": "Search root (workspace-relative, default '.').",
            },
            "exact": {
                "type": "boolean",
                "description": "When true, match filename exactly (default false).",
            },
        },
        "required": ["name"],
    },
    large_result=True,
)
async def find_file_tool(
    ctx: ToolContext,
    name: str,
    path: str = ".",
    exact: bool = False,
) -> str:
    """Walk ``path`` and return filenames matching ``name``.

    Args:
        ctx (ToolContext): Invocation context.
        name (str): Filename or substring to search for.
        path (str): Workspace-relative search root.
        exact (bool): Require exact basename match when ``True``.

    Returns:
        str: §3.1 JSON envelope with ``paths`` list (capped).

    Examples:
        >>> find_file_tool.__name__
        'find_file_tool'
    """
    root = ctx.workspace_path
    needle = name.strip()
    if not needle:
        return enveloped_failure("name must be non-empty", code=ToolResultCode.VALIDATION_ERROR)
    try:
        base, rel_base = resolve_tool_path(root, path, checkout=ctx.checkout_path)
    except (PermissionError, WorkspacePathError) as exc:
        return _path_error_envelope(exc)
    if not base.is_dir():
        return enveloped_failure(f"not a directory: {path}", code=ToolResultCode.VALIDATION_ERROR)

    hits: list[str] = []
    truncated = False
    for directory, _dirnames, filenames in _walk_visible(root, base):
        for filename in filenames:
            matched = filename == needle if exact else needle in filename
            if not matched:
                continue
            candidate = (directory / filename).resolve()
            if is_llmignored(candidate, root):
                continue
            hits.append(
                display_path_for_tool(root, candidate),
            )
            if len(hits) >= MAX_LISTING_RESULTS:
                truncated = True
                return enveloped_success(
                    {
                        "name": needle,
                        "base": rel_base,
                        "paths": hits,
                        "count": len(hits),
                        "truncated": truncated,
                        "exact": exact,
                    },
                )
    return enveloped_success(
        {
            "name": needle,
            "base": rel_base,
            "paths": hits,
            "count": len(hits),
            "truncated": truncated,
            "exact": exact,
        },
    )


def _walk_visible(workspace: Path, base: Path) -> list[tuple[Path, list[str], list[str]]]:
    """Walk ``base`` skipping ``.llmignore`` directories during filename discovery.

    Args:
        workspace (Path): Workspace content root.
        base (Path): Resolved search root directory.

    Returns:
        list[tuple[Path, list[str], list[str]]]: ``(directory, dirnames, filenames)`` rows.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> d = ws / "tree"
        >>> _ = d.mkdir()
        >>> _ = (d / "leaf.txt").write_text("", encoding="utf-8")
        >>> rows = _walk_visible(ws, d.resolve())
        >>> rows[0][2]
        ['leaf.txt']
    """
    rows: list[tuple[Path, list[str], list[str]]] = []
    stack: list[Path] = [base]
    while stack:
        current = stack.pop()
        if is_llmignored(current, workspace):
            continue
        dirnames: list[str] = []
        filenames: list[str] = []
        try:
            for child in sorted(current.iterdir(), key=lambda item: item.name.lower()):
                if is_llmignored(child, workspace):
                    continue
                if child.is_dir():
                    dirnames.append(child.name)
                    stack.append(child)
                elif child.is_file():
                    filenames.append(child.name)
        except OSError:
            continue
        rows.append((current, dirnames, filenames))
    return rows


@sevn_tool(
    name="file_info",
    category="file_ops",
    description="Return metadata (size, mtime, type, mode) for one workspace path.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative path.",
            },
        },
        "required": ["path"],
    },
)
async def file_info_tool(ctx: ToolContext, path: str) -> str:
    """Stat one workspace path and return descriptive metadata.

    Args:
        ctx (ToolContext): Invocation context.
        path (str): Workspace-relative file or directory path.

    Returns:
        str: §3.1 JSON envelope with stat fields or validation errors.

    Examples:
        >>> file_info_tool.__name__
        'file_info_tool'
    """
    root = ctx.workspace_path
    try:
        target, rel = resolve_tool_path(root, path, checkout=ctx.checkout_path)
    except (PermissionError, WorkspacePathError) as exc:
        return _path_error_envelope(exc)
    if not target.exists():
        return enveloped_failure(f"not found: {path}", code=ToolResultCode.VALIDATION_ERROR)
    try:
        st = target.stat()
    except OSError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.INTERNAL_ERROR)
    kind = "directory" if target.is_dir() else "file" if target.is_file() else "other"
    return enveloped_success(
        {
            "path": rel,
            "type": kind,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat(),
            "mode": stat.filemode(st.st_mode),
        },
    )


__all__ = [
    "file_info_tool",
    "find_file_tool",
    "glob_tool",
    "list_dir_tool",
]
