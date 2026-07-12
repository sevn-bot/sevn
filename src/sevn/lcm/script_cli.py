"""Shared CLI helpers for bundled ``lcm`` skill scripts.

Module: sevn.lcm.script_cli
Depends: json, pathlib, sqlite3, sevn.storage

Exports:
    workspace_from_env — resolve ``SEVN_WORKSPACE``.
    open_workspace_db — connect to migrated ``sevn.db``.
    session_key_from — CLI arg with ``SEVN_SESSION_KEY`` fallback.
    write_ok — emit success JSON envelope on stdout.
    write_error — emit failure JSON envelope on stdout.
    cap_script_row_limit — clamp bundled script ``--limit`` values.

Bundled-script stdout contract (P4 / skill runner P3):
    * Success: ``write_ok(...)`` then ``return 0``.
    * Failure: ``write_error(code=..., error=...)`` then ``return 1``.
    * The skill runner prefers a well-formed ``{"ok":false,…}`` stdout envelope
      over a generic nonzero-exit mask even when the exit code is ``1``; keep
      stderr quiet for expected failures so stdout stays a single JSON object.

Examples:
    >>> from sevn.lcm.script_cli import workspace_from_env
    >>> isinstance(workspace_from_env(), type(workspace_from_env()))
    True
"""

from __future__ import annotations

import json
import os
import sqlite3  # noqa: TC003 — public API return type
import sys
from pathlib import Path

from sevn.storage import open_sevn_sqlite

DEFAULT_SCRIPT_ROW_LIMIT = 20
MAX_SCRIPT_ROW_LIMIT = 200


def cap_script_row_limit(limit: int) -> int:
    """Clamp bundled script ``--limit`` values to ``1..MAX_SCRIPT_ROW_LIMIT``.

    Args:
        limit (int): Requested row cap from CLI args.

    Returns:
        int: Clamped cap suitable for LCM/gateway query helpers.

    Examples:
        >>> cap_script_row_limit(0)
        1
        >>> cap_script_row_limit(999)
        200
    """
    return max(1, min(int(limit), MAX_SCRIPT_ROW_LIMIT))


def workspace_from_env() -> Path:
    """Return resolved workspace root from ``SEVN_WORKSPACE``.

    Returns:
        Path: Absolute workspace content root.

    Examples:
        >>> workspace_from_env().is_absolute()
        True
    """
    return Path(os.environ.get("SEVN_WORKSPACE", ".")).resolve()


def open_workspace_db(workspace: Path | None = None) -> sqlite3.Connection:
    """Open workspace ``sevn.db`` with migrations applied.

    Args:
        workspace (Path | None, optional): Content root; defaults to :func:`workspace_from_env`.

    Returns:
        sqlite3.Connection: Migrated connection (caller should close).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> _ = (ws / ".sevn").mkdir(parents=True)
        >>> conn = open_workspace_db(ws)
        >>> isinstance(conn, sqlite3.Connection)
        True
        >>> conn.close()
    """
    root = workspace if workspace is not None else workspace_from_env()
    dot_sevn = root / ".sevn"
    return open_sevn_sqlite(dot_sevn)


def session_key_from(*, cli_value: str | None) -> str:
    """Resolve session key from CLI or ``SEVN_SESSION_KEY`` env.

    Args:
        cli_value (str | None): ``--session-key`` value when set.

    Returns:
        str: Resolved session key (may be empty).

    Examples:
        >>> session_key_from(cli_value="web:abc")
        'web:abc'
    """
    if cli_value:
        return cli_value.strip()
    return os.environ.get("SEVN_SESSION_KEY", "").strip()


def write_ok(data: object, *, message: str | None = None) -> None:
    """Write a success tool envelope to stdout.

    Args:
        data (object): JSON-serialisable payload.
        message (str | None, optional): Optional human message. Defaults to ``None``.

    Examples:
        >>> import io
        >>> from contextlib import redirect_stdout
        >>> buf = io.StringIO()
        >>> with redirect_stdout(buf):
        ...     write_ok({"n": 1})
        >>> '"ok":true' in buf.getvalue()
        True
    """
    sys.stdout.write(
        json.dumps({"ok": True, "data": data, "message": message}, separators=(",", ":")),
    )


def write_error(*, code: str, error: str) -> None:
    """Write a failure tool envelope to stdout.

    Args:
        code (str): Stable error code.
        error (str): Human-readable detail.

    Examples:
        >>> import io
        >>> from contextlib import redirect_stdout
        >>> buf = io.StringIO()
        >>> with redirect_stdout(buf):
        ...     write_error(code="VALIDATION_ERROR", error="bad")
        >>> '"ok":false' in buf.getvalue()
        True
    """
    sys.stdout.write(
        json.dumps(
            {"ok": False, "error": error, "code": code},
            separators=(",", ":"),
        ),
    )
