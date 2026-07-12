"""Line-numbered ``read`` tool for workspace files and directories (`specs/11-tools-registry.md` §4.3).

Module: sevn.tools.file_ops.read
Depends: sevn.tools.base, sevn.tools.context, sevn.tools.decorator, sevn.tools.paths

Exports:
    read_tool — ``@sevn_tool`` callable registered by :func:`register_file_ops_tools`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sevn.config.defaults import TOOL_LARGE_RESULT_THRESHOLD_BYTES
from sevn.tools.base import enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool
from sevn.tools.paths import (
    WorkspacePathError,
    filter_visible_entries,
    resolve_tool_path,
)

# Default page size (lines) applied to a file read when no explicit ``limit`` is
# given and the numbered output would exceed the inline byte threshold. Paging
# returns the first page plus a ``next_offset`` cursor instead of spilling the
# whole file (`specs/11-tools-registry.md` §4.3).
DEFAULT_READ_PAGE_LINES = 800


def _file_read_envelope_bytes(
    *,
    rel: str,
    lines: list[str],
    start: int,
    total_lines: int,
    mtime: str,
    next_offset: int | None = None,
) -> int:
    """Return UTF-8 byte length of the §3.1 success envelope for a file read page.

    Args:
        rel (str): Workspace-relative path in the payload.
        lines (list[str]): Raw lines for this page (without numbering).
        start (int): 1-based line number of ``lines[0]``.
        total_lines (int): Whole-file line count.
        mtime (str): ISO mtime string for the payload.
        next_offset (int | None): Optional 1-based start of the next page.

    Returns:
        int: Byte length of :func:`enveloped_success` output for this page.

    Examples:
        >>> _file_read_envelope_bytes(
        ...     rel="a.txt",
        ...     lines=["hi"],
        ...     start=1,
        ...     total_lines=1,
        ...     mtime="2026-01-01T00:00:00+00:00",
        ... ) > 0
        True
    """
    numbered = _format_line_numbered(lines, start=start)
    payload: dict[str, object] = {
        "path": rel,
        "kind": "file",
        "content": numbered,
        "line_count": len(lines),
        "total_lines": total_lines,
        "mtime": mtime,
    }
    if next_offset is not None:
        payload["next_offset"] = next_offset
    return len(enveloped_success(payload).encode("utf-8"))


def _fit_read_page(
    lines: list[str],
    *,
    start: int,
    total_lines: int,
    rel: str,
    mtime: str,
) -> tuple[list[str], int | None]:
    """Shrink a candidate page until its success envelope fits the inline budget.

    Args:
        lines (list[str]): Remaining file lines from ``start`` onward.
        start (int): 1-based line number of ``lines[0]``.
        total_lines (int): Whole-file line count.
        rel (str): Workspace-relative path.
        mtime (str): ISO mtime string.

    Returns:
        tuple[list[str], int | None]: Page lines and optional ``next_offset`` cursor.

    Examples:
        >>> page, nxt = _fit_read_page(
        ...     ["a", "b"],
        ...     start=1,
        ...     total_lines=2,
        ...     rel="t.txt",
        ...     mtime="2026-01-01T00:00:00+00:00",
        ... )
        >>> len(page) == 2 and nxt is None
        True
    """
    if not lines:
        return [], None
    page_count = min(DEFAULT_READ_PAGE_LINES, len(lines))
    while page_count > 1:
        page_lines = lines[:page_count]
        candidate = start + len(page_lines)
        next_offset = candidate if candidate <= total_lines else None
        if (
            _file_read_envelope_bytes(
                rel=rel,
                lines=page_lines,
                start=start,
                total_lines=total_lines,
                mtime=mtime,
                next_offset=next_offset,
            )
            <= TOOL_LARGE_RESULT_THRESHOLD_BYTES
        ):
            return page_lines, next_offset
        page_count = max(1, page_count // 2)
    page_lines = lines[:1]
    candidate = start + 1
    next_offset = candidate if candidate <= total_lines else None
    return page_lines, next_offset


def _format_line_numbered(lines: list[str], *, start: int = 1) -> str:
    """Prefix each line with ``N|`` for agent-facing read output.

    Args:
        lines (list[str]): Raw text lines without numbering.
        start (int): First line number (1-based).

    Returns:
        str: Joined ``line|content`` rows separated by newlines.

    Examples:
        >>> _format_line_numbered(["a", "b"], start=1)
        '1|a\\n2|b'
    """
    return "\n".join(f"{index}|{line}" for index, line in enumerate(lines, start=start))


def _directory_listing_text(workspace: Path, directory: Path) -> str:
    """Build a line-numbered directory listing for ``read`` on directories.

    Args:
        workspace (Path): Workspace content root.
        directory (Path): Resolved directory path.

    Returns:
        str: Line-numbered listing; directories suffixed with ``/``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> d = ws / "src"
        >>> _ = d.mkdir()
        >>> _ = (d / "main.py").write_text("", encoding="utf-8")
        >>> "main.py" in _directory_listing_text(ws, d.resolve())
        True
    """
    rows: list[str] = []
    for child in filter_visible_entries(workspace, directory):
        label = f"{child.name}/" if child.is_dir() else child.name
        rows.append(label)
    if not rows:
        return _format_line_numbered(["(empty directory)"], start=1)
    return _format_line_numbered(rows, start=1)


def _path_error_envelope(exc: BaseException) -> str:
    """Map filesystem guard failures to §3.1 envelopes.

    Args:
        exc (BaseException): Raised guard or I/O error.

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


@sevn_tool(
    name="read",
    category="file_ops",
    description="Read a workspace file (line-numbered) or list a directory.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative path (e.g. source_code/sevn/gateway/agent_turn.py).",
            },
            "offset": {
                "type": "integer",
                "minimum": 1,
                "description": "1-based start line when reading a file (optional).",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum lines to return when reading a file (optional).",
            },
        },
        "required": ["path"],
    },
    large_result=True,
)
async def read_tool(
    ctx: ToolContext,
    path: str,
    offset: int | None = None,
    limit: int | None = None,
) -> str:
    """Read a file with line numbers or list a directory when ``path`` is a folder.

    When ``limit`` is omitted and the numbered output would exceed the inline
    byte threshold (``TOOL_LARGE_RESULT_THRESHOLD_BYTES``), the read is capped to
    :data:`DEFAULT_READ_PAGE_LINES` lines and the payload carries a
    ``next_offset`` cursor (1-based start line of the next page). Pass that value
    back as ``offset`` to continue. ``total_lines`` always reflects the whole
    file so the caller knows how far is left. A read that fits inline returns no
    ``next_offset``.

    Args:
        ctx (ToolContext): Invocation context (``workspace_path`` is content root).
        path (str): Workspace-relative path to a file or directory.
        offset (int | None): Optional 1-based start line for file reads.
        limit (int | None): Optional maximum number of lines for file reads.

    Returns:
        str: §3.1 JSON envelope with ``content`` text or validation/permission errors.

    Examples:
        >>> read_tool.__name__
        'read_tool'
    """
    root = ctx.workspace_path
    try:
        target, rel = resolve_tool_path(root, path, checkout=ctx.checkout_path)
    except (PermissionError, WorkspacePathError) as exc:
        return _path_error_envelope(exc)

    if target.is_dir():
        content = _directory_listing_text(root, target)
        payload: dict[str, object] = {
            "path": rel,
            "kind": "directory",
            "content": content,
            "line_count": content.count("\n") + (1 if content else 0),
        }
        return enveloped_success(payload)

    if not target.is_file():
        return enveloped_failure(
            f"not found: {path}",
            code=ToolResultCode.VALIDATION_ERROR,
            data={
                "path": path,
                "error": "not_found",
                "hint": "do_not_reconstruct",
            },
        )

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.INTERNAL_ERROR)

    all_lines = text.splitlines()
    total_lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    start = 1 if offset is None else max(1, offset)
    lines = all_lines[start - 1 :] if offset is not None else list(all_lines)
    if limit is not None:
        lines = lines[: max(0, limit)]

    mtime = datetime.fromtimestamp(target.stat().st_mtime, tz=UTC).isoformat()

    # Paging: when no explicit limit was given and the full read would exceed
    # the inline budget, return the largest prefix that fits plus a cursor
    # instead of spilling the whole file (D2).
    next_offset: int | None = None
    if (
        limit is None
        and _file_read_envelope_bytes(
            rel=rel,
            lines=lines,
            start=start,
            total_lines=total_lines,
            mtime=mtime,
        )
        > TOOL_LARGE_RESULT_THRESHOLD_BYTES
    ):
        lines, next_offset = _fit_read_page(
            lines,
            start=start,
            total_lines=total_lines,
            rel=rel,
            mtime=mtime,
        )

    numbered = _format_line_numbered(lines, start=start)
    file_payload: dict[str, object] = {
        "path": rel,
        "kind": "file",
        "content": numbered,
        "line_count": len(lines),
        "total_lines": total_lines,
        "mtime": mtime,
    }
    if next_offset is not None:
        file_payload["next_offset"] = next_offset
    return enveloped_success(file_payload)


__all__ = ["read_tool"]
