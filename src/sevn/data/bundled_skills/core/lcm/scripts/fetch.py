#!/usr/bin/env python3
"""Bundled ``lcm`` skill — fetch message(s) with full text.

Module: sevn.data.bundled_skills.core.lcm.scripts.fetch
Depends: argparse, sevn.lcm.query, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.lcm.query import fetch_message, fetch_recent_messages, list_conversations
from sevn.lcm.script_cli import open_workspace_db, session_key_from, write_error, write_ok


def main() -> int:
    """Fetch one message by id, or the recent tail for a session.

    With ``--message-id`` returns that message; with ``--session-key`` returns that
    session's recent tail; with **neither**, defaults to the most-recent conversation
    (recall fallback) so "fetch the last session" works without a list-first call.

    Returns:
        int: ``0`` on success; ``1`` when the LCM index is empty / lookup fails.

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
        ...     "visible_to_llm, status, created_at) VALUES (?, 1, 'user', 'full body', "
        ...     "'message', 1, 'sent', '2026-01-01')",
        ...     (cid,),
        ... )
        >>> conn.commit()
        >>> conn.close()
        >>> buf = io.StringIO()
        >>> argv = sys.argv
        >>> try:
        ...     sys.argv = ["fetch", "--session-key", "k1"]
        ...     with redirect_stdout(buf):
        ...         rc = main()
        ... finally:
        ...     sys.argv = argv
        >>> rc == 0
        True
        >>> buf2 = io.StringIO()  # no args → defaults to most-recent conversation
        >>> try:
        ...     sys.argv = ["fetch"]
        ...     with redirect_stdout(buf2):
        ...         rc2 = main()
        ... finally:
        ...     sys.argv = argv
        >>> rc2 == 0 and '"defaulted_to_latest":true' in buf2.getvalue()
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--message-id", type=int, default=None)
    parser.add_argument("--session-key", default=None)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    conn = open_workspace_db()
    try:
        if args.message_id is not None:
            payload = fetch_message(conn, message_id=args.message_id)
            write_ok({"mode": "single", "message": payload})
            return 0
        session_key = session_key_from(cli_value=args.session_key)
        defaulted = False
        if not session_key:
            # Recall fallback: default to the most-recent conversation so "fetch the last
            # session" works without a list-first round-trip (transcript-review-2026-06-22).
            recent = list_conversations(conn, limit=1)
            if recent:
                session_key = str(recent[0]["session_key"])
                defaulted = True
        if not session_key:
            write_error(
                code="NOT_FOUND",
                error="no conversations found (LCM index empty)",
            )
            return 1
        messages = fetch_recent_messages(conn, session_key=session_key, limit=args.limit)
    except (LookupError, ValueError) as exc:
        write_error(
            code="NOT_FOUND" if isinstance(exc, LookupError) else "VALIDATION_ERROR", error=str(exc)
        )
        return 1
    finally:
        conn.close()
    write_ok(
        {
            "mode": "recent",
            "session_key": session_key,
            "defaulted_to_latest": defaulted,
            "messages": messages,
            "count": len(messages),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
