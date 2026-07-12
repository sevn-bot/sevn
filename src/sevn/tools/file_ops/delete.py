"""Workspace ``delete`` tool with human gate (`specs/11-tools-registry.md` §8).

Module: sevn.tools.file_ops.delete
Depends: sevn.tools.base, sevn.tools.context, sevn.tools.decorator, sevn.tools.paths

Exports:
    delete_tool — remove a file or directory tree after human acknowledgement.
"""

from __future__ import annotations

import shutil

from sevn.tools.base import enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool
from sevn.tools.paths import (
    WorkspacePathError,
    resolve_workspace_relative_path,
)


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


@sevn_tool(
    name="delete",
    category="file_ops",
    description="Delete a workspace file or directory tree (requires human approval).",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to workspace root."},
        },
        "required": ["path"],
    },
    requires_human=True,
    abortable=False,
)
async def delete_tool(ctx: ToolContext, path: str) -> str:
    """Delete ``path`` when the executor has acknowledged the human gate.

    Args:
        ctx (ToolContext): Invocation context.
        path (str): Workspace-relative file or directory path.

    Returns:
        str: §3.1 JSON envelope with deletion metadata or validation errors.

    Examples:
        >>> delete_tool.__name__
        'delete_tool'
    """
    root = ctx.workspace_path
    try:
        target = resolve_workspace_relative_path(root, path)
    except (PermissionError, WorkspacePathError) as exc:
        return _path_error_envelope(exc)

    rel = target.relative_to(root.expanduser().resolve()).as_posix()

    if not target.exists():
        return enveloped_failure(
            f"not found: {path}",
            code=ToolResultCode.VALIDATION_ERROR,
        )

    kind = "directory" if target.is_dir() else "file"
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except OSError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.INTERNAL_ERROR)

    return enveloped_success({"path": rel, "kind": kind, "deleted": True})


__all__ = ["delete_tool"]
