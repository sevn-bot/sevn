#!/usr/bin/env python3
"""Bundled ``sessions_management`` skill — session run-state snapshot.

Module: sevn.data.bundled_skills.core.sessions_management.scripts.status
Depends: argparse, sevn.gateway.sessions_query, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import os

from sevn.gateway.sessions_query import session_status_snapshot
from sevn.lcm.script_cli import open_workspace_db, write_error, write_ok


def _session_id_from(cli_value: str | None) -> str | None:
    """Resolve session id from CLI or ``SEVN_SESSION_ID``.

    Args:
        cli_value (str | None): ``--session-id`` when set.

    Returns:
        str | None: Resolved id or ``None``.

    Examples:
        >>> _session_id_from("s")
        's'
    """
    if cli_value and cli_value.strip():
        return cli_value.strip()
    env = os.environ.get("SEVN_SESSION_ID", "").strip()
    return env or None


def main() -> int:
    """Run session status CLI.

    Returns:
        int: ``0`` on success; ``1`` on validation failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", default=None)
    args = parser.parse_args()
    session_id = _session_id_from(args.session_id)
    if not session_id:
        write_error(code="VALIDATION_ERROR", error="--session-id or SEVN_SESSION_ID required")
        return 1
    conn = open_workspace_db()
    try:
        data = session_status_snapshot(conn, session_id, caller_session_id=session_id)
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1
    finally:
        conn.close()
    write_ok(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
