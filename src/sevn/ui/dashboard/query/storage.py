"""Parameterized ``sevn.db`` readers for Mission Control.

Module: sevn.ui.dashboard.query.storage
Depends: json, sqlite3

Exports:
    list_gateway_sessions — session summaries for the Sessions tab.
    list_active_run_snapshots — active run snapshot summaries.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def _loads_dict(raw: str | None) -> dict[str, object]:
    """Parse JSON object payload defensively.

    Args:
        raw (str | None): Serialized JSON or empty.

    Returns:
        dict[str, object]: Parsed mapping or empty dict.

    Examples:
        >>> _loads_dict('{"a": 1}')
        {'a': 1}
        >>> _loads_dict(None)
        {}
    """

    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def list_gateway_sessions(conn: sqlite3.Connection, *, limit: int) -> dict[str, object]:
    """Return gateway session summaries.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` connection.
        limit (int): Clamped page size.

    Returns:
        dict[str, object]: ``items`` / ``next_cursor`` / ``has_more`` page.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> list_gateway_sessions(conn, limit=1)["items"]
        []
        >>> conn.close()
    """

    rows = conn.execute(
        """
        SELECT s.session_id, s.scope_key, s.channel, s.user_id, s.created_at, s.updated_at,
               s.metadata_json,
               (SELECT COUNT(1) FROM active_run_snapshots a
                WHERE a.session_id = s.session_id AND a.status = 'active') AS active_runs
        FROM gateway_sessions s
        ORDER BY s.updated_at DESC, s.session_id ASC
        LIMIT ?
        """,
        (limit + 1,),
    ).fetchall()
    items = [
        {
            "session_id": row[0],
            "scope_key": row[1],
            "channel": row[2],
            "user_id": row[3],
            "created_at": row[4],
            "updated_at": row[5],
            "metadata": _loads_dict(row[6]),
            "active_runs": int(row[7] or 0),
        }
        for row in rows
    ]
    next_cursor = items[limit - 1]["updated_at"] if len(items) > limit else None
    return {"items": items[:limit], "next_cursor": next_cursor, "has_more": next_cursor is not None}


def list_active_run_snapshots(conn: sqlite3.Connection, *, limit: int) -> dict[str, object]:
    """Return active run snapshot summaries.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` connection.
        limit (int): Clamped page size.

    Returns:
        dict[str, object]: ``items`` / ``next_cursor`` / ``has_more`` page.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> list_active_run_snapshots(conn, limit=1)["items"]
        []
        >>> conn.close()
    """

    rows = conn.execute(
        """
        SELECT run_id, session_id, tier, excerpt, status, created_at_ns, updated_at_ns
        FROM active_run_snapshots
        ORDER BY updated_at_ns DESC, run_id ASC
        LIMIT ?
        """,
        (limit + 1,),
    ).fetchall()
    items: list[dict[str, Any]] = [
        {
            "run_id": row[0],
            "session_id": row[1],
            "tier": row[2],
            "excerpt": row[3],
            "status": row[4],
            "created_at_ns": row[5],
            "updated_at_ns": row[6],
        }
        for row in rows
    ]
    next_cursor = str(items[limit - 1]["updated_at_ns"]) if len(items) > limit else None
    return {"items": items[:limit], "next_cursor": next_cursor, "has_more": next_cursor is not None}
