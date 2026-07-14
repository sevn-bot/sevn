#!/usr/bin/env python3
"""Bundled ``sessions_management`` skill — record session yield.

Module: sevn.data.bundled_skills.core.sessions_management.scripts.yield
Depends: argparse, json, sevn.gateway.session.sessions_query, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import json
import os

from sevn.gateway.session.sessions_query import record_yield
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
    """Run sessions yield CLI.

    Returns:
        int: ``0`` on success; ``1`` on validation failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--reason", default=None)
    parser.add_argument("--delegate-to", default=None)
    parser.add_argument("--delegate-message", default=None)
    parser.add_argument("--payload-json", default=None)
    args = parser.parse_args()
    session_id = _session_id_from(args.session_id)
    if not session_id:
        write_error(code="VALIDATION_ERROR", error="--session-id or SEVN_SESSION_ID required")
        return 1
    payload: dict[str, object] | None = None
    if args.payload_json:
        try:
            parsed = json.loads(args.payload_json)
        except json.JSONDecodeError as exc:
            write_error(code="VALIDATION_ERROR", error=f"invalid payload JSON: {exc}")
            return 1
        if not isinstance(parsed, dict):
            write_error(code="VALIDATION_ERROR", error="payload-json must be a JSON object")
            return 1
        payload = parsed
    conn = open_workspace_db()
    try:
        result = record_yield(
            conn,
            session_id,
            caller_session_id=session_id,
            payload=payload,
            reason=args.reason,
            delegate_to=args.delegate_to,
            delegate_message=args.delegate_message,
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
