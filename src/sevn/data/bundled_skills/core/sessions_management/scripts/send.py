#!/usr/bin/env python3
"""Bundled ``sessions_management`` skill — post to another session.

Module: sevn.data.bundled_skills.core.sessions_management.scripts.send
Depends: argparse, sevn.gateway.session.sessions_query, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import os

from sevn.gateway.session.sessions_query import send_to_session
from sevn.lcm.script_cli import open_workspace_db, write_error, write_ok


def _session_id_from(cli_value: str | None) -> str | None:
    """Resolve caller session id from CLI or ``SEVN_SESSION_ID``.

    Args:
        cli_value (str | None): ``--caller-session-id`` when set.

    Returns:
        str | None: Resolved id or ``None``.

    Examples:
        >>> _session_id_from("x")
        'x'
    """
    if cli_value and cli_value.strip():
        return cli_value.strip()
    env = os.environ.get("SEVN_SESSION_ID", "").strip()
    return env or None


def main() -> int:
    """Run sessions send CLI.

    Returns:
        int: ``0`` on success; ``1`` on validation failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--role", default="user", choices=("user", "system"))
    parser.add_argument("--caller-session-id", default=None)
    args = parser.parse_args()
    caller = _session_id_from(args.caller_session_id)
    conn = open_workspace_db()
    try:
        result = send_to_session(
            conn,
            args.session_id.strip(),
            args.text,
            caller_session_id=caller,
            role=args.role,
        )
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1
    finally:
        conn.close()
    write_ok(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
