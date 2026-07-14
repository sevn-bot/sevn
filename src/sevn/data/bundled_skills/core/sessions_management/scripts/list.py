#!/usr/bin/env python3
"""Bundled ``sessions_management`` skill — list gateway sessions.

Module: sevn.data.bundled_skills.core.sessions_management.scripts.list
Depends: argparse, sevn.gateway.session.sessions_query, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import os

from sevn.gateway.session.sessions_query import list_sessions
from sevn.lcm.script_cli import open_workspace_db, write_error, write_ok


def _session_id_from(cli_value: str | None) -> str | None:
    """Resolve caller session id from CLI or ``SEVN_SESSION_ID``.

    Args:
        cli_value (str | None): ``--session-id`` when set.

    Returns:
        str | None: Resolved id or ``None``.

    Examples:
        >>> _session_id_from("abc")
        'abc'
    """
    if cli_value and cli_value.strip():
        return cli_value.strip()
    env = os.environ.get("SEVN_SESSION_ID", "").strip()
    return env or None


def main() -> int:
    """Run sessions list CLI.

    Returns:
        int: ``0`` on success; ``1`` on validation failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--channel", default=None)
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    caller = _session_id_from(args.session_id)
    conn = open_workspace_db()
    try:
        items = list_sessions(
            conn,
            caller_session_id=caller,
            channel=args.channel,
            user_id=args.user_id,
            date_from=args.date_from,
            date_to=args.date_to,
            limit=args.limit,
        )
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1
    finally:
        conn.close()
    write_ok({"sessions": items, "count": len(items)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
