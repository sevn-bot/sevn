"""Stub tables for ``memory_search`` recall telemetry (`specs/31-memory-dreaming.md` §3.1).

Module: sevn.memory.search_telemetry
Depends: sqlite3, uuid, datetime

Exports:
    record_memory_search_event — append a federated search row (stub hook).
    record_memory_recall_signal — append a recall-weight row for Dreaming.
    load_recall_weights — map ``memory_key`` → weight for scorer enrichment.

Examples:
    >>> import sqlite3
    >>> from sevn.storage.migrate import apply_migrations
    >>> from sevn.memory.search_telemetry import record_memory_search_event
    >>> c = sqlite3.connect(":memory:")
    >>> apply_migrations(c)
    >>> _ = record_memory_search_event(
    ...     c, session_id="s", query_text="q", source="all", result_count=0
    ... )
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Final

_RECALL_DEFAULT: Final[float] = 1.0


def _iso_now() -> str:
    """Return UTC ISO timestamp for telemetry rows.

    Returns:
        str: ``YYYY-MM-DDTHH:MM:SS+00:00`` style timestamp.

    Examples:
        >>> "T" in _iso_now()
        True
    """

    return datetime.now(tz=UTC).isoformat()


def record_memory_search_event(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    query_text: str,
    source: str,
    result_count: int,
) -> str:
    """Insert one ``memory_search_events`` row (no-op when table missing).

    Args:
        conn (sqlite3.Connection): Workspace ``sevn.db`` connection.
        session_id (str): Owner session scope.
        query_text (str): Query string (truncated to 4096 chars).
        source (str): Branch label, e.g. ``all`` / ``memory`` / ``markdown``.
        result_count (int): Merged hit count returned to the tool.

    Returns:
        str: New row ``event_id``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> eid = record_memory_search_event(
        ...     c, session_id="dm:u", query_text="prefs", source="all", result_count=3
        ... )
        >>> len(eid) >= 8
        True
    """

    event_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO memory_search_events (
            event_id, session_id, query_text, source, result_count, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            session_id,
            query_text[:4096],
            source[:64],
            int(result_count),
            _iso_now(),
        ),
    )
    conn.commit()
    return event_id


def record_memory_recall_signal(
    conn: sqlite3.Connection,
    *,
    memory_key: str,
    session_id: str,
    recall_weight: float = 1.0,
) -> str:
    """Insert one ``memory_recall_signals`` row for Dreaming scorer hooks.

    Args:
        conn (sqlite3.Connection): Workspace ``sevn.db`` connection.
        memory_key (str): Short-term memory key or composite id.
        session_id (str): Session scope for the recall.
        recall_weight (float): Non-negative weight in ``[0, 1]`` (clamped).

    Returns:
        str: New row ``signal_id``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> sid = record_memory_recall_signal(
        ...     c, memory_key="k1", session_id="dm:u", recall_weight=0.8
        ... )
        >>> bool(sid)
        True
    """

    signal_id = uuid.uuid4().hex
    w = max(0.0, min(1.0, float(recall_weight)))
    conn.execute(
        """
        INSERT INTO memory_recall_signals (
            signal_id, memory_key, session_id, recall_weight, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (signal_id, memory_key[:512], session_id[:256], w, _iso_now()),
    )
    conn.commit()
    return signal_id


def load_recall_weights(conn: sqlite3.Connection, *, limit: int = 2000) -> dict[str, float]:
    """Load latest recall weight per ``memory_key`` (newest row wins).

    Args:
        conn (sqlite3.Connection): Workspace ``sevn.db`` connection.
        limit (int): Row scan cap.

    Returns:
        dict[str, float]: ``memory_key`` → recall weight.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _ = record_memory_recall_signal(c, memory_key="k", session_id="s", recall_weight=0.5)
        >>> load_recall_weights(c)["k"] == 0.5
        True
    """

    cur = conn.execute(
        """
        SELECT memory_key, recall_weight, created_at
        FROM memory_recall_signals
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (int(limit),),
    )
    out: dict[str, float] = {}
    for key, weight, _created in cur.fetchall():
        k = str(key)
        if k not in out:
            out[k] = float(weight)
    return out


__all__ = [
    "load_recall_weights",
    "record_memory_recall_signal",
    "record_memory_search_event",
]
