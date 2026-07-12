"""Session-summary keyword search over ``lcm_summaries``.

Module: sevn.lcm.search
Depends: (none)

Exports:
    search_session_summaries — LIKE-based keyword query (`specs/15-memory-lcm.md` §3.3).

Examples:
    >>> import sqlite3
    >>> from sevn.lcm.search import search_session_summaries
    >>> search_session_summaries(sqlite3.connect(":memory:"),
    ...     query="x", date_from=None, date_to=None, limit=1,
    ...     conversation_ids_filter=None)
    Traceback (most recent call last):
    ...
    sqlite3.OperationalError: ...
"""

from __future__ import annotations

import sqlite3  # noqa: TC003 — public API takes ``sqlite3.Connection``
from typing import Any

_MAX_SUMMARY_SEARCH_LIMIT = 200


def _cap_summary_limit(limit: int) -> int:
    """Clamp summary search row caps to ``1.._MAX_SUMMARY_SEARCH_LIMIT``.

    Args:
        limit (int): Requested row cap.

    Returns:
        int: Clamped cap.

    Examples:
        >>> _cap_summary_limit(0)
        1
    """
    return max(1, min(int(limit), _MAX_SUMMARY_SEARCH_LIMIT))


def search_session_summaries(
    conn: sqlite3.Connection,
    *,
    query: str,
    date_from: str | None,
    date_to: str | None,
    limit: int,
    conversation_ids_filter: list[int] | None,
) -> list[dict[str, Any]]:
    """Return matching session-end summaries with optional date + conversation filters.

        Args:
    conn (sqlite3.Connection): Workspace DB.
    query (str): Keyword substring (escaped for LIKE).
    date_from (str | None): Inclusive ``created_at`` lower bound (ISO text).
    date_to (str | None): Inclusive ``created_at`` upper bound (ISO text).
    limit (int): Row cap.
    conversation_ids_filter (list[int] | None): Restrict to these conversations.

        Returns:
            list[dict[str, Any]]: Hits newest-first.

        Examples:
            >>> import sqlite3
            >>> search_session_summaries(sqlite3.connect(":memory:"),
            ...     query="hi", date_from=None, date_to=None, limit=1,
            ...     conversation_ids_filter=None)
            Traceback (most recent call last):
            ...
            sqlite3.OperationalError: ...
    """
    like_pat = f"%{query.replace('%', r'\%').replace('_', r'\_')}%"
    sql_parts = [
        """
        SELECT s.summary_id, s.conversation_id, s.content, s.created_at,
               c.session_key, c.channel
        FROM lcm_summaries s
        JOIN lcm_conversations c ON c.id = s.conversation_id
        WHERE s.summary_kind = 'session_end'
          AND s.content LIKE ? ESCAPE '\\'
        """,
    ]
    params: list[Any] = [like_pat]
    if date_from:
        sql_parts.append("AND s.created_at >= ?")
        params.append(date_from)
    if date_to:
        sql_parts.append("AND s.created_at <= ?")
        params.append(date_to)
    if conversation_ids_filter:
        placeholders = ",".join("?" for _ in conversation_ids_filter)
        sql_parts.append(f"AND s.conversation_id IN ({placeholders})")
        params.extend(conversation_ids_filter)
    sql_parts.append("ORDER BY s.created_at DESC LIMIT ?")
    params.append(_cap_summary_limit(limit))
    sql = "".join(sql_parts)
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "summary_id": row[0],
                "conversation_id": int(row[1]),
                "content": row[2],
                "created_at": row[3],
                "session_key": row[4],
                "channel": row[5],
            },
        )
    return out
