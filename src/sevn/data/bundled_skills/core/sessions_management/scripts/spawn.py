#!/usr/bin/env python3
"""Bundled ``sessions_management`` skill — spawn subagent session.

Module: sevn.data.bundled_skills.core.sessions_management.scripts.spawn
Depends: argparse, sevn.gateway.session.sessions_query, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import os

from sevn.gateway.session.sessions_query import spawn_subagent
from sevn.lcm.script_cli import open_workspace_db, write_error, write_ok


def _session_id_from(cli_value: str | None) -> str | None:
    """Resolve caller session id from CLI or ``SEVN_SESSION_ID``.

    Args:
        cli_value (str | None): ``--caller-session-id`` when set.

    Returns:
        str | None: Resolved id or ``None``.

    Examples:
        >>> _session_id_from("p")
        'p'
    """
    if cli_value and cli_value.strip():
        return cli_value.strip()
    env = os.environ.get("SEVN_SESSION_ID", "").strip()
    return env or None


def main() -> int:
    """Run sessions spawn CLI.

    Returns:
        int: ``0`` on success; ``1`` on validation failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-session-id", required=True)
    parser.add_argument("--system-prompt", default=None)
    parser.add_argument("--tool", action="append", default=None)
    parser.add_argument("--caller-session-id", default=None)
    args = parser.parse_args()
    caller = _session_id_from(args.caller_session_id)
    conn = open_workspace_db()
    try:
        result = spawn_subagent(
            conn,
            args.parent_session_id.strip(),
            caller_session_id=caller,
            system_prompt=args.system_prompt,
            tool_allowlist=args.tool,
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
