"""Webhook dedupe persistence (`specs/30-non-interactive-triggers.md` §3.2).

Module: sevn.triggers.dedupe
Depends: sqlite3, time

Exports:
    try_insert_webhook_dedupe — first-seen vs duplicate.
    prune_webhook_dedupe_expired — TTL garbage collection.

Examples:
    >>> from sevn.triggers.dedupe import try_insert_webhook_dedupe
    >>> try_insert_webhook_dedupe.__name__
    'try_insert_webhook_dedupe'
"""

from __future__ import annotations

import sqlite3
import time
from typing import Literal

DedupeInsert = Literal["inserted", "duplicate"]


def try_insert_webhook_dedupe(
    conn: sqlite3.Connection,
    *,
    source: str,
    delivery_id: str,
    correlation_id: str,
    ttl_s: int,
) -> DedupeInsert:
    """Insert dedupe row or detect duplicate primary key.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` connection.
        source (str): Webhook source key (e.g. ``github``).
        delivery_id (str): Provider stable delivery id.
        correlation_id (str): Assigned correlation id for this acceptance.
        ttl_s (int): Seconds until ``expire_at_ns``.

    Returns:
        DedupeInsert: ``inserted`` on first sight, ``duplicate`` otherwise.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> from sevn.triggers.dedupe import try_insert_webhook_dedupe
        >>> try_insert_webhook_dedupe(
        ...     c, source="s", delivery_id="d", correlation_id="x", ttl_s=60,
        ... ) == "inserted"
        True
    """
    now_ns = time.time_ns()
    expire_at_ns = now_ns + int(ttl_s) * 1_000_000_000
    try:
        conn.execute(
            """
            INSERT INTO trigger_webhook_dedupe (
                source, delivery_id, first_seen_ns, expire_at_ns, correlation_id
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (source, delivery_id, now_ns, expire_at_ns, correlation_id),
        )
    except sqlite3.IntegrityError:
        return "duplicate"
    conn.commit()
    return "inserted"


def prune_webhook_dedupe_expired(conn: sqlite3.Connection, *, now_ns: int | None = None) -> int:
    """Delete expired dedupe rows (call from gateway boot + cron tick).

    Args:
        conn (sqlite3.Connection): Database connection.
        now_ns (int | None): Monotonic clock nanoseconds; default ``time.time_ns()``.

    Returns:
        int: Rows deleted.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> from sevn.triggers.dedupe import prune_webhook_dedupe_expired
        >>> prune_webhook_dedupe_expired(c, now_ns=999) == 0
        True
    """
    cutoff = int(now_ns if now_ns is not None else time.time_ns())
    cur = conn.execute("DELETE FROM trigger_webhook_dedupe WHERE expire_at_ns < ?", (cutoff,))
    n = int(cur.rowcount or 0)
    conn.commit()
    return n
