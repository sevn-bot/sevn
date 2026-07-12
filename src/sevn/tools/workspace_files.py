"""Bootstrap-safe workspace markdown writes (`plan/operator-experience-wave-plan.md` Wave 3).

Module: sevn.tools.workspace_files
Depends: pathlib, sevn.tools.base, sevn.tools.context

Exports:
    write_workspace_md — atomic write under ``content_root``.
    register_write_workspace_md — register ``write_workspace_md`` on a ``ToolExecutor``.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Final

from sevn.tools.base import FunctionTool, ToolDefinition, enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode

if TYPE_CHECKING:
    from sevn.tools.base import ToolExecutor
    from sevn.tools.context import ToolContext

ALLOWED_WORKSPACE_MD: Final[frozenset[str]] = frozenset(
    {"USER.md", "SOUL.md", "IDENTITY.md", "MEMORY.md"},
)
_USER_INCOMPLETE_MARKER: Final[str] = "<!-- sevn-bootstrap:user-incomplete -->"


def write_workspace_md(content_root: Path, filename: str, content: str) -> Path:
    """Write one allowlisted markdown file under ``content_root`` (atomic).

    Args:
        content_root (Path): Resolved workspace content root.
        filename (str): Basename only (e.g. ``USER.md``).
        content (str): Full file body.

    Returns:
        Path: Written file path.

    Raises:
        ValueError: When ``filename`` is not allowlisted or path escapes root.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     p = write_workspace_md(root, "USER.md", "- **Name:** Alex\\n")
        ...     p.name
        'USER.md'
    """
    name = Path(filename).name
    if name not in ALLOWED_WORKSPACE_MD:
        msg = f"workspace write not allowed for {filename!r}"
        raise ValueError(msg)
    target = (content_root / name).resolve()
    root = content_root.expanduser().resolve()
    if not str(target).startswith(str(root)):
        msg = f"path escapes workspace root: {filename!r}"
        raise ValueError(msg)
    root.mkdir(parents=True, exist_ok=True)
    body = content
    if (
        name == "USER.md"
        and _USER_INCOMPLETE_MARKER in body
        and "- **Name:**" in body
        and "_(your name)_" not in body
        and "_(you)_" not in body
    ):
        body = body.replace(_USER_INCOMPLETE_MARKER, "").strip() + "\n"
    fd, tmp = tempfile.mkstemp(dir=root, prefix=f".{name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return target


async def _write_workspace_md_tool(ctx: ToolContext, *, path: str, content: str) -> str:
    """Tool body for ``write_workspace_md``.

    Args:
        ctx (ToolContext): Invocation context (``workspace_path`` is content root).
        path (str): Allowlisted filename.
        content (str): Markdown body.

    Returns:
        str: §3.1 JSON envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_write_workspace_md_tool)
        True
    """
    try:
        written = write_workspace_md(ctx.workspace_path, path, content)
    except ValueError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)
    except OSError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.INTERNAL_ERROR)
    return enveloped_success({"path": str(written.name), "bytes": written.stat().st_size})


def register_write_workspace_md(executor: ToolExecutor) -> None:
    """Register ``write_workspace_md`` for bootstrap tier-B turns.

    Args:
        executor (ToolExecutor): Session registry executor.

    Returns:
        None

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.workspace_files import register_write_workspace_md
        >>> exe = ToolExecutor()
        >>> register_write_workspace_md(exe)
        >>> any(d.name == "write_workspace_md" for d in exe.definitions())
        True
    """
    defn = ToolDefinition(
        name="write_workspace_md",
        category="workspace",
        description=(
            "Write bootstrap narrative markdown (USER.md, SOUL.md, IDENTITY.md, MEMORY.md only)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Filename: USER.md, SOUL.md, IDENTITY.md, or MEMORY.md",
                },
                "content": {"type": "string", "description": "Full markdown file body"},
            },
            "required": ["path", "content"],
        },
    )
    executor.register(FunctionTool(defn, _write_workspace_md_tool))


__all__ = [
    "ALLOWED_WORKSPACE_MD",
    "register_write_workspace_md",
    "write_workspace_md",
]
