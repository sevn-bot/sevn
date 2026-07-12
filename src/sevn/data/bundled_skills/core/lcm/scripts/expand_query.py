#!/usr/bin/env python3
"""Bundled ``lcm`` skill — multi-term query expansion.

Module: sevn.data.bundled_skills.core.lcm.scripts.expand_query
Depends: argparse, sevn.lcm.query, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.lcm.query import expand_query
from sevn.lcm.script_cli import open_workspace_db, session_key_from, write_error, write_ok


def main() -> int:
    """Run expand-query CLI (deterministic term split + grep merge).

    Returns:
        int: ``0`` on success; ``1`` on validation failure.

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
        ...     "INSERT INTO lcm_messages (conversation_id, seq, role, content, kind, "
        ...     "visible_to_llm, status, created_at) VALUES (?, 1, 'user', 'deploy fix', "
        ...     "'message', 1, 'sent', '2026-01-01')",
        ...     (cid,),
        ... )
        >>> conn.commit()
        >>> conn.close()
        >>> buf = io.StringIO()
        >>> argv = sys.argv
        >>> try:
        ...     sys.argv = ["expand_query", "--query", "deploy", "--session-key", "k1"]
        ...     with redirect_stdout(buf):
        ...         rc = main()
        ... finally:
        ...     sys.argv = argv
        >>> rc == 0
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--session-key", default=None)
    parser.add_argument(
        "--scope",
        default="conversation",
        choices=("workspace", "conversation", "same_telegram_topic"),
    )
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    session_key = session_key_from(cli_value=args.session_key) or None
    scope = args.scope
    conn = open_workspace_db()
    try:
        payload = expand_query(
            conn,
            query=args.query,
            scope=scope,
            session_key=session_key,
            limit=args.limit,
        )
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1
    finally:
        conn.close()
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
