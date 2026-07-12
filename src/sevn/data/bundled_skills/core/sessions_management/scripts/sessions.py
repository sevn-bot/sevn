#!/usr/bin/env python3
"""Bundled ``sessions_management`` skill — legacy sessions alias.

Module: sevn.data.bundled_skills.core.sessions_management.scripts.sessions
Depends: argparse, sevn.gateway.sessions_query, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import os

from sevn.gateway.sessions_query import (
    fetch_session_history,
    list_sessions,
    send_to_session,
)
from sevn.lcm.script_cli import open_workspace_db, write_error, write_ok


def _session_id_from(cli_value: str | None) -> str | None:
    """Resolve caller session id from CLI or ``SEVN_SESSION_ID``.

    Args:
        cli_value (str | None): ``--session-id`` when set.

    Returns:
        str | None: Resolved id or ``None``.

    Examples:
        >>> _session_id_from("c")
        'c'
    """
    if cli_value and cli_value.strip():
        return cli_value.strip()
    env = os.environ.get("SEVN_SESSION_ID", "").strip()
    return env or None


def main() -> int:
    """Run legacy ``sessions`` compatibility CLI.

    Returns:
        int: ``0`` on success; ``1`` on validation failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=("list", "send", "get"))
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--text", default=None)
    parser.add_argument("--channel", default=None)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    caller = _session_id_from(args.session_id if args.action == "list" else None)
    conn = open_workspace_db()
    try:
        if args.action == "list":
            items = list_sessions(
                conn,
                caller_session_id=caller,
                channel=args.channel,
                limit=args.limit,
            )
            data: dict[str, object] = {"sessions": items, "count": len(items)}
        elif args.action == "send":
            if not args.session_id or not args.text:
                write_error(
                    code="VALIDATION_ERROR",
                    error="send requires --session-id and --text",
                )
                return 1
            data = send_to_session(
                conn,
                args.session_id.strip(),
                args.text,
                caller_session_id=_session_id_from(None),
            )
        else:
            if not args.session_id:
                write_error(code="VALIDATION_ERROR", error="get requires --session-id")
                return 1
            data = fetch_session_history(
                conn,
                args.session_id.strip(),
                caller_session_id=_session_id_from(None),
                limit=args.limit,
            )
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1
    finally:
        conn.close()
    write_ok(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
