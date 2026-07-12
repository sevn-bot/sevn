"""Mutating workspace file tools except ``delete`` (`specs/11-tools-registry.md` §4.3).

Module: sevn.tools.file_ops.write
Depends: sevn.tools.base, sevn.tools.context, sevn.tools.decorator, sevn.tools.paths

Exports:
    write_tool — overwrite or create a file with atomic write.
    edit_tool — unique-string replace in an existing file.
    create_folder_tool — mkdir -p under workspace root.
    move_file_tool — move or rename a path.
    copy_file_tool — copy a file or directory tree.
    atomic_write_text — shared temp-file + replace helper.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from pathlib import Path

from sevn.tools.base import enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool
from sevn.tools.paths import (
    WorkspacePathError,
    resolve_artifact_tool_path,
    resolve_workspace_relative_path,
)


def _path_error_envelope(exc: BaseException) -> str:
    """Map guard failures to §3.1 envelopes.

    Args:
        exc (BaseException): Raised guard or validation error.

    Returns:
        str: JSON failure envelope string.

    Examples:
        >>> "VALIDATION_ERROR" in _path_error_envelope(WorkspacePathError("bad"))
        True
    """
    if isinstance(exc, PermissionError):
        return enveloped_failure(str(exc), code=ToolResultCode.PERMISSION_DENIED)
    if isinstance(exc, WorkspacePathError):
        return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)
    return enveloped_failure(str(exc), code=ToolResultCode.INTERNAL_ERROR)


def atomic_write_text(target: Path, content: str) -> None:
    """Write ``content`` to ``target`` via temp file and atomic ``os.replace``.

    Args:
        target (Path): Destination file path (parent dirs are created).
        content (str): UTF-8 text body.

    Returns:
        None

    Raises:
        OSError: When the filesystem write or rename fails.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     p = Path(td) / "nested" / "out.txt"
        ...     atomic_write_text(p, "hello")
        ...     p.read_text(encoding="utf-8")
        'hello'
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _resolve(
    ctx: ToolContext,
    rel_path: str,
    *,
    allow_existing_outside: bool = False,
) -> tuple[Path, str] | str:
    """Resolve ``rel_path`` or return a failure envelope string.

    Args:
        ctx (ToolContext): Invocation context.
        rel_path (str): Workspace-relative path.
        allow_existing_outside (bool, optional): When true, keep existing files at
            their literal path (used by ``edit``). Defaults to ``False``.

    Returns:
        tuple[Path, str] | str: ``(absolute, relative_posix)`` or JSON failure envelope.

    Examples:
        >>> _resolve.__name__
        '_resolve'
    """
    root = ctx.workspace_path
    prefix = ctx.artifact_output_prefix.strip()
    try:
        if prefix:
            target, rel = resolve_artifact_tool_path(
                root,
                rel_path,
                output_prefix=prefix,
                allow_existing_outside=allow_existing_outside,
            )
        else:
            target = resolve_workspace_relative_path(root, rel_path)
            rel = target.relative_to(root.expanduser().resolve()).as_posix()
    except (PermissionError, WorkspacePathError) as exc:
        return _path_error_envelope(exc)
    return target, rel


def _resolve_source(ctx: ToolContext, rel_path: str) -> tuple[Path, str] | str:
    """Resolve a read/move/copy source path without artifact rebasing.

    Args:
        ctx (ToolContext): Invocation context.
        rel_path (str): Workspace-relative source path.

    Returns:
        tuple[Path, str] | str: ``(absolute, relative_posix)`` or JSON failure envelope.

    Examples:
        >>> _resolve_source.__name__
        '_resolve_source'
    """
    root = ctx.workspace_path
    try:
        target = resolve_workspace_relative_path(root, rel_path)
    except (PermissionError, WorkspacePathError) as exc:
        return _path_error_envelope(exc)
    rel = target.relative_to(root.expanduser().resolve()).as_posix()
    return target, rel


@sevn_tool(
    name="write",
    category="file_ops",
    description="Write or overwrite a workspace file; create parent directories.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to workspace root."},
            "content": {"type": "string", "description": "Full UTF-8 file body."},
        },
        "required": ["path", "content"],
    },
)
async def write_tool(ctx: ToolContext, path: str, content: str) -> str:
    """Write ``content`` to ``path``, replacing any existing file atomically.

    Args:
        ctx (ToolContext): Invocation context (``workspace_path`` is content root).
        path (str): Workspace-relative destination path.
        content (str): Full file body.

    Returns:
        str: §3.1 JSON envelope with written path metadata or validation errors.

    Examples:
        >>> write_tool.__name__
        'write_tool'
    """
    resolved = _resolve(ctx, path)
    if isinstance(resolved, str):
        return resolved
    target, rel = resolved
    if target.is_dir():
        return enveloped_failure(
            f"path is a directory: {path}",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    try:
        atomic_write_text(target, content)
    except OSError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.INTERNAL_ERROR)
    return enveloped_success({"path": rel, "bytes_written": len(content.encode("utf-8"))})


@sevn_tool(
    name="edit",
    category="file_ops",
    description="Replace exactly one unique occurrence of old_string in a file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to workspace root."},
            "old_string": {
                "type": "string",
                "description": "Exact substring to replace (must be unique).",
            },
            "new_string": {"type": "string", "description": "Replacement text."},
        },
        "required": ["path", "old_string", "new_string"],
    },
)
async def edit_tool(
    ctx: ToolContext,
    path: str,
    old_string: str,
    new_string: str,
) -> str:
    """Perform a surgical unique-string replace in an existing workspace file.

    Args:
        ctx (ToolContext): Invocation context.
        path (str): Workspace-relative file path.
        old_string (str): Exact substring that must appear exactly once.
        new_string (str): Replacement text.

    Returns:
        str: §3.1 JSON envelope with edit metadata or validation errors.

    Examples:
        >>> edit_tool.__name__
        'edit_tool'
    """
    resolved = _resolve(ctx, path, allow_existing_outside=True)
    if isinstance(resolved, str):
        return resolved
    target, rel = resolved
    if not target.is_file():
        return enveloped_failure(
            f"not a file: {path}",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.INTERNAL_ERROR)
    count = text.count(old_string)
    if count == 0:
        return enveloped_failure(
            "old_string not found in file",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    if count > 1:
        return enveloped_failure(
            f"old_string is not unique ({count} occurrences)",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    updated = text.replace(old_string, new_string, 1)
    try:
        atomic_write_text(target, updated)
    except OSError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.INTERNAL_ERROR)
    return enveloped_success(
        {
            "path": rel,
            "replacements": 1,
            "bytes_written": len(updated.encode("utf-8")),
        },
    )


@sevn_tool(
    name="create_folder",
    category="file_ops",
    description="Create a workspace directory (mkdir -p).",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path relative to workspace root."},
        },
        "required": ["path"],
    },
)
async def create_folder_tool(ctx: ToolContext, path: str) -> str:
    """Create ``path`` and any missing parent directories under the workspace.

    Args:
        ctx (ToolContext): Invocation context.
        path (str): Workspace-relative directory path.

    Returns:
        str: §3.1 JSON envelope with created path metadata.

    Examples:
        >>> create_folder_tool.__name__
        'create_folder_tool'
    """
    resolved = _resolve(ctx, path)
    if isinstance(resolved, str):
        return resolved
    target, rel = resolved
    if target.exists() and not target.is_dir():
        return enveloped_failure(
            f"path exists and is not a directory: {path}",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.INTERNAL_ERROR)
    return enveloped_success({"path": rel, "created": True})


@sevn_tool(
    name="move_file",
    category="file_ops",
    description="Move or rename a workspace file or directory.",
    parameters={
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Source path relative to workspace root."},
            "destination": {
                "type": "string",
                "description": "Destination path relative to workspace root.",
            },
        },
        "required": ["source", "destination"],
    },
)
async def move_file_tool(ctx: ToolContext, source: str, destination: str) -> str:
    """Move ``source`` to ``destination`` within the workspace.

    Args:
        ctx (ToolContext): Invocation context.
        source (str): Workspace-relative source path.
        destination (str): Workspace-relative destination path.

    Returns:
        str: §3.1 JSON envelope with moved path metadata.

    Examples:
        >>> move_file_tool.__name__
        'move_file_tool'
    """
    src_resolved = _resolve_source(ctx, source)
    if isinstance(src_resolved, str):
        return src_resolved
    src_path, _src_rel = src_resolved
    dst_resolved = _resolve(ctx, destination)
    if isinstance(dst_resolved, str):
        return dst_resolved
    dst_path, dst_rel = dst_resolved
    if not src_path.exists():
        return enveloped_failure(
            f"source not found: {source}",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    if dst_path.exists():
        return enveloped_failure(
            f"destination already exists: {destination}",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    try:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))
    except OSError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.INTERNAL_ERROR)
    return enveloped_success({"source": source, "destination": dst_rel, "moved": True})


@sevn_tool(
    name="copy_file",
    category="file_ops",
    description="Copy a workspace file or directory tree to a new path.",
    parameters={
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Source path relative to workspace root."},
            "destination": {
                "type": "string",
                "description": "Destination path relative to workspace root.",
            },
        },
        "required": ["source", "destination"],
    },
)
async def copy_file_tool(ctx: ToolContext, source: str, destination: str) -> str:
    """Copy ``source`` to ``destination`` within the workspace.

    Args:
        ctx (ToolContext): Invocation context.
        source (str): Workspace-relative source path.
        destination (str): Workspace-relative destination path.

    Returns:
        str: §3.1 JSON envelope with copied path metadata.

    Examples:
        >>> copy_file_tool.__name__
        'copy_file_tool'
    """
    src_resolved = _resolve_source(ctx, source)
    if isinstance(src_resolved, str):
        return src_resolved
    src_path, src_rel = src_resolved
    dst_resolved = _resolve(ctx, destination)
    if isinstance(dst_resolved, str):
        return dst_resolved
    dst_path, dst_rel = dst_resolved
    if not src_path.exists():
        return enveloped_failure(
            f"source not found: {source}",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    if dst_path.exists():
        return enveloped_failure(
            f"destination already exists: {destination}",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    try:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if src_path.is_dir():
            shutil.copytree(src_path, dst_path)
            kind = "directory"
        else:
            shutil.copy2(src_path, dst_path)
            kind = "file"
    except OSError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.INTERNAL_ERROR)
    return enveloped_success(
        {"source": src_rel, "destination": dst_rel, "kind": kind, "copied": True},
    )


__all__ = [
    "atomic_write_text",
    "copy_file_tool",
    "create_folder_tool",
    "edit_tool",
    "move_file_tool",
    "write_tool",
]
