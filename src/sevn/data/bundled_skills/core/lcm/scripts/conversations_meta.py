#!/usr/bin/env python3
"""Bundled ``lcm`` skill — conversation metadata and counts.

Module: sevn.data.bundled_skills.core.lcm.scripts.conversations_meta
Depends: argparse, sevn.lcm.query, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.lcm.query import conversations_meta
from sevn.lcm.script_cli import open_workspace_db, write_error, write_ok


def main() -> int:
    """Return metadata rows for one or more conversation ids.

    Returns:
        int: ``0`` on success; ``1`` when no ids supplied.

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
        ...     "VALUES ('k1', 'web', '2026-01-01', '2026-01-01')"
        ... )
        >>> cid = int(conn.execute("SELECT id FROM lcm_conversations").fetchone()[0])
        >>> conn.commit()
        >>> conn.close()
        >>> buf = io.StringIO()
        >>> argv = sys.argv
        >>> try:
        ...     sys.argv = ["conversations_meta", "--conversation-id", str(cid)]
        ...     with redirect_stdout(buf):
        ...         rc = main()
        ... finally:
        ...     sys.argv = argv
        >>> rc == 0
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--conversation-id", type=int, action="append", default=[])
    args = parser.parse_args()
    if not args.conversation_id:
        write_error(code="VALIDATION_ERROR", error="at least one --conversation-id required")
        return 1
    conn = open_workspace_db()
    try:
        rows = conversations_meta(conn, conversation_ids=args.conversation_id)
    finally:
        conn.close()
    write_ok({"conversations": rows, "count": len(rows)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
