#!/usr/bin/env python3
"""Bundled ``lcm`` skill — canonical status summary.

Module: sevn.data.bundled_skills.core.lcm.scripts.status
Depends: sevn.lcm.script_cli, sqlite3

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

from sevn.lcm.script_cli import open_workspace_db, write_ok


def main() -> int:
    """Emit a compact LCM status snapshot for operator checks.

    Returns:
        int: ``0`` on success.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    conn = open_workspace_db()
    try:
        conversations = int(conn.execute("SELECT COUNT(*) FROM lcm_conversations").fetchone()[0])
        messages = int(conn.execute("SELECT COUNT(*) FROM lcm_messages").fetchone()[0])
        summaries = int(conn.execute("SELECT COUNT(*) FROM lcm_summaries").fetchone()[0])
        last_summary = conn.execute(
            "SELECT created_at FROM lcm_summaries ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    write_ok(
        {
            "status": "ok",
            "counts": {
                "conversations": conversations,
                "messages": messages,
                "summaries": summaries,
            },
            "last_summary_created_at": last_summary[0] if last_summary else None,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
