"""Operator-readable MCP server event log under ``<workspace>/logs/mcp.log`` (#90, W29.4).

Module: sevn.tools.mcp_logging
Depends: json, pathlib, loguru

Exports:
    append_mcp_log — append one structured JSON line for operator review.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

MCP_LOG_FILENAME: str = "mcp.log"
"""Basename for MCP stdio discovery/call events (``specs/11-tools-registry.md`` W29)."""


def _logs_dir(workspace_path: Path | None) -> Path | None:
    """Return ``<workspace>/logs`` when a workspace root is known.

    Args:
        workspace_path (Path | None): Workspace content root.

    Returns:
        Path | None: Logs directory path, or ``None`` when unset.

    Examples:
        >>> from pathlib import Path
        >>> _logs_dir(Path("/tmp/w")).name
        'logs'
        >>> _logs_dir(None) is None
        True
    """
    if workspace_path is None:
        return None
    return workspace_path / "logs"


def append_mcp_log(
    workspace_path: Path | None,
    event: str,
    *,
    server_id: str | None = None,
    tool_name: str | None = None,
    level: str = "info",
    **fields: Any,
) -> None:
    """Append one JSON log line to ``<workspace>/logs/mcp.log`` and mirror to loguru.

    Args:
        workspace_path (Path | None): Workspace content root; when ``None`` only loguru is used.
        event (str): Short event name (``discover_failed``, ``call_failed``, …).
        server_id (str | None): MCP server id when known.
        tool_name (str | None): Upstream tool name when known.
        level (str): ``info`` | ``warning`` | ``error`` for loguru routing.
        fields (Any): Additional JSON-safe metadata passed as keyword arguments.

    Returns:
        None

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     append_mcp_log(root, "discover_ok", server_id="demo", tool_count=1)
        ...     (root / "logs" / "mcp.log").exists()
        True
    """
    row: dict[str, Any] = {
        "ts": datetime.now(tz=UTC).isoformat(),
        "event": event,
    }
    if server_id is not None:
        row["server_id"] = server_id
    if tool_name is not None:
        row["tool_name"] = tool_name
    row.update(fields)
    line = json.dumps(row, ensure_ascii=False, sort_keys=True)

    log_fn = logger.info
    if level == "warning":
        log_fn = logger.warning
    elif level == "error":
        log_fn = logger.error
    log_fn("mcp_event: {}", line)

    logs_dir = _logs_dir(workspace_path)
    if logs_dir is None:
        return
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        with (logs_dir / MCP_LOG_FILENAME).open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as exc:
        logger.warning("mcp_log_write_failed: {}", exc)


__all__ = ["MCP_LOG_FILENAME", "append_mcp_log"]
