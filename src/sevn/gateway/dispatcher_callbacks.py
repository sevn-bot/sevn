"""``dispatcher_callbacks`` table maintenance (`specs/17-gateway.md` §3.4).

Module: sevn.gateway.dispatcher_callbacks
Depends: sqlite3, datetime

Exports:
    prune_dispatcher_callbacks — delete dedupe rows older than a TTL.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta


def prune_dispatcher_callbacks(conn: sqlite3.Connection, *, ttl_seconds: int) -> int:
    """Delete rows whose ``created_at`` is older than ``ttl_seconds`` (UTC).

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle (migration ≥3).
        ttl_seconds (int): Retention window in seconds.

    Returns:
        int: Number of rows deleted (``sqlite3.Cursor.rowcount``).

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> prune_dispatcher_callbacks(c, ttl_seconds=3600) >= 0
        True
        >>> c.close()
    """

    cutoff = (
        (datetime.now(tz=UTC) - timedelta(seconds=max(0, ttl_seconds)))
        .replace(
            tzinfo=None,
        )
        .isoformat()
    )
    cur = conn.execute(
        "DELETE FROM dispatcher_callbacks WHERE created_at < ?",
        (cutoff,),
    )
    conn.commit()
    return int(cur.rowcount or 0)
