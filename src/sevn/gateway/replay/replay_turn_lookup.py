"""Lookup replayable user text for dashboard turn replay.

Module: sevn.gateway.replay.replay_turn_lookup
Depends: sqlite3

Exports:
    lookup_user_text_for_turn — recover user message text from ``gateway_messages``.
"""

from __future__ import annotations

import sqlite3


def lookup_user_text_for_turn(
    conn: sqlite3.Connection,
    session_id: str,
    turn_id: str,
) -> str | None:
    """Return replayable user text for ``(session_id, turn_id)`` when present.

    Dashboard replay requires a persisted user ``kind='message'`` row with
    non-empty content. Command-only turns (``kind != 'message'``) and slash
    commands are not replayable.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        session_id (str): Gateway session id.
        turn_id (str): User turn id to replay.

    Returns:
        str | None: Trimmed user text, or ``None`` when not replayable.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.gateway.replay.replay_turn_lookup import lookup_user_text_for_turn
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> lookup_user_text_for_turn(c, "s", "t") is None
        True
    """
    row = conn.execute(
        """
        SELECT content, kind
        FROM gateway_messages
        WHERE session_id = ?
          AND turn_id = ?
          AND role = 'user'
        ORDER BY id DESC
        LIMIT 1
        """,
        (session_id, turn_id),
    ).fetchone()
    if row is None:
        return None
    content, kind = str(row[0] or ""), str(row[1] or "")
    if kind != "message":
        return None
    text = content.strip()
    if not text or text.startswith("/"):
        return None
    return text


__all__ = ["lookup_user_text_for_turn"]
