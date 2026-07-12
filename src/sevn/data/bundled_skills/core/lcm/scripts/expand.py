#!/usr/bin/env python3
"""Bundled ``lcm`` skill — summary DAG expansion.

Module: sevn.data.bundled_skills.core.lcm.scripts.expand
Depends: argparse, sevn.lcm.query, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.lcm.query import expand_summary
from sevn.lcm.script_cli import open_workspace_db, write_error, write_ok


def main() -> int:
    """Run expand CLI for one summary id.

    Returns:
        int: ``0`` on success; ``1`` when the summary is missing.

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
        >>> _ = conn.execute(
        ...     "INSERT INTO lcm_summaries (summary_id, conversation_id, content, depth, "
        ...     "summary_kind, created_at) VALUES ('s1', ?, 'summary text', 0, "
        ...     "'compaction', '2026-01-01')",
        ...     (cid,),
        ... )
        >>> conn.commit()
        >>> conn.close()
        >>> buf = io.StringIO()
        >>> argv = sys.argv
        >>> try:
        ...     sys.argv = ["expand", "--summary-id", "s1"]
        ...     with redirect_stdout(buf):
        ...         rc = main()
        ... finally:
        ...     sys.argv = argv
        >>> rc == 0
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary-id", required=True)
    args = parser.parse_args()
    conn = open_workspace_db()
    try:
        payload = expand_summary(conn, summary_id=args.summary_id)
    except LookupError as exc:
        write_error(code="NOT_FOUND", error=str(exc))
        return 1
    finally:
        conn.close()
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
