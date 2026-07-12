"""FTS5 trace search for Mission Control global search.

Module: sevn.ui.dashboard.query.search
Depends: re, sqlite3

Exports:
    fts_query_text — sanitize user input for FTS5 MATCH.
    search_trace_events — unified trace search page.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any


def fts_query_text(raw: str) -> str:
    """Turn free-text input into a safe FTS5 MATCH expression.

    Args:
        raw (str): User search text.

    Returns:
        str: FTS5 query or empty string when no tokens remain.

    Examples:
        >>> fts_query_text("ripgrep tool")
        '"ripgrep" AND "tool"'
        >>> fts_query_text("  ")
        ''
    """

    tokens = [t for t in re.split(r"\s+", raw.strip()) if t]
    if not tokens:
        return ""
    return " AND ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)


def search_trace_events(
    conn: sqlite3.Connection,
    *,
    query: str,
    limit: int,
) -> dict[str, object]:
    """Search ``trace_events`` via ``trace_events_fts`` (``specs/04-tracing.md`` §10.7).

    Args:
        conn (sqlite3.Connection): Open ``traces.db`` connection.
        query (str): Free-text search string.
        limit (int): Clamped page size.

    Returns:
        dict[str, object]: ``items`` / ``next_cursor`` / ``has_more`` page.

    Examples:
        >>> import sqlite3
        >>> from sevn.agent.tracing.traces_migrate import apply_traces_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_traces_migrations(conn)
        >>> search_trace_events(conn, query="", limit=5)["items"]
        []
        >>> conn.close()
    """

    match = fts_query_text(query)
    if not match:
        return {"items": [], "next_cursor": None, "has_more": False}
    has_fts = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'trace_events_fts' LIMIT 1",
    ).fetchone()
    if not has_fts:
        return {"items": [], "next_cursor": None, "has_more": False}
    rows = conn.execute(
        """
        SELECT e.span_id, e.session_id, e.turn_id, e.tier, e.kind,
               e.ts_start_ns, e.status
        FROM trace_events_fts f
        JOIN trace_events e ON e.rowid = f.rowid
        WHERE trace_events_fts MATCH ?
        ORDER BY e.ts_start_ns DESC
        LIMIT ?
        """,
        (match, limit + 1),
    ).fetchall()
    items: list[dict[str, Any]] = [
        {
            "span_id": row[0],
            "session_id": row[1],
            "turn_id": row[2],
            "tier": row[3],
            "kind": row[4],
            "ts_start_ns": row[5],
            "status": row[6],
        }
        for row in rows
    ]
    next_cursor = str(items[limit - 1]["ts_start_ns"]) if len(items) > limit else None
    return {"items": items[:limit], "next_cursor": next_cursor, "has_more": next_cursor is not None}
