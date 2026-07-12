#!/usr/bin/env python3
"""Bundled ``lcm`` skill — light conversation index.

Module: sevn.data.bundled_skills.core.lcm.scripts.list_conversations
Depends: argparse, sevn.lcm.query, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.lcm.query import list_conversations
from sevn.lcm.script_cli import open_workspace_db, write_ok


def main() -> int:
    """List LCM conversations with optional date filters.

    Returns:
        int: ``0`` on success.

    Examples:
        >>> import io, os, sys, tempfile
        >>> from contextlib import redirect_stdout
        >>> from pathlib import Path
        >>> from sevn.storage.migrate import apply_migrations
        >>> base = tempfile.mkdtemp()
        >>> os.environ["SEVN_WORKSPACE"] = base
        >>> db = Path(base) / ".sevn" / "sevn.db"
        >>> db.parent.mkdir(parents=True, exist_ok=True)
        >>> conn = __import__("sqlite3").connect(str(db))
        >>> apply_migrations(conn)
        >>> _ = conn.execute(
        ...     "INSERT INTO lcm_conversations (session_key, channel, created_at, updated_at) "
        ...     "VALUES ('k1', 'web', '2026-01-01', '2026-01-02')"
        ... )
        >>> conn.commit()
        >>> conn.close()
        >>> buf = io.StringIO()
        >>> argv = sys.argv
        >>> try:
        ...     sys.argv = ["list_conversations"]
        ...     with redirect_stdout(buf):
        ...         rc = main()
        ... finally:
        ...     sys.argv = argv
        >>> rc == 0
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    conn = open_workspace_db()
    try:
        rows = list_conversations(
            conn,
            date_from=args.date_from,
            date_to=args.date_to,
            limit=args.limit,
        )
    finally:
        conn.close()
    write_ok({"conversations": rows, "count": len(rows)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
