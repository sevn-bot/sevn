#!/usr/bin/env python3
"""Bundled ``sessions_management`` skill — session history and search.

Module: sevn.data.bundled_skills.core.sessions_management.scripts.history
Depends: argparse, sevn.gateway.session.sessions_query, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import os

from sevn.gateway.session.sessions_query import (
    MAX_HISTORY_LIMIT,
    cap_history_limit,
    fetch_session_history,
    search_messages,
)
from sevn.lcm.script_cli import open_workspace_db, write_error, write_ok


def _session_id_from(cli_value: str | None) -> str | None:
    """Resolve caller session id from CLI or ``SEVN_SESSION_ID``.

    Args:
        cli_value (str | None): ``--session-id`` when set.

    Returns:
        str | None: Resolved id or ``None``.

    Examples:
        >>> _session_id_from(None) is None or isinstance(_session_id_from(None), str)
        True
    """
    if cli_value and cli_value.strip():
        return cli_value.strip()
    env = os.environ.get("SEVN_SESSION_ID", "").strip()
    return env or None


def main() -> int:
    """Run sessions history CLI.

    Returns:
        int: ``0`` on success; ``1`` on validation failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--query", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    if args.limit < 1 or args.limit > MAX_HISTORY_LIMIT:
        write_error(
            code="VALIDATION_ERROR",
            error=f"limit must be 1..{MAX_HISTORY_LIMIT}",
        )
        return 1
    capped_limit = cap_history_limit(args.limit)
    caller = _session_id_from(None)
    conn = open_workspace_db()
    try:
        if args.session_id and args.session_id.strip():
            data = fetch_session_history(
                conn,
                args.session_id.strip(),
                caller_session_id=caller,
                query=args.query,
                limit=capped_limit,
                offset=args.offset,
                full=args.full,
            )
        elif args.query and args.query.strip():
            hits = search_messages(
                conn,
                args.query.strip(),
                caller_session_id=caller,
                limit=capped_limit,
                full=args.full,
            )
            data = {"hits": hits, "count": len(hits)}
        else:
            write_error(
                code="VALIDATION_ERROR",
                error="provide --session-id or --query",
            )
            return 1
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1
    finally:
        conn.close()
    write_ok(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
