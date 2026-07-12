"""Audit timeline and analytics aggregations from ``traces.db``.

Module: sevn.ui.dashboard.query.audit_analytics
Depends: sqlite3, time, sevn.agent.tracing.redacting_sink, sevn.ui.dashboard.query.traces

Exports:
    audit_timeline_from_traces — paginated mission audit timeline.
    tool_frequency_from_traces — tool-call counts by tool name.
    daily_volume_from_traces — daily event volume from hourly rollups.
    approval_timeline_from_traces — mission approval audit rows.
"""

from __future__ import annotations

import sqlite3
import time

from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy
from sevn.ui.dashboard.query.traces import list_trace_events

_NS_PER_DAY = 86_400 * 1_000_000_000
_AUDIT_KIND_PREFIXES = ("tool.", "channel.", "mission.", "provider.", "b_")


def _days_to_ns(days: int) -> int:
    """Convert a day window to nanoseconds for ``ts_start_ns`` cutoffs.

    Args:
        days (int): Lookback window in days (minimum 1).

    Returns:
        int: Nanoseconds span for the window.

    Examples:
        >>> _days_to_ns(1) == 86_400 * 1_000_000_000
        True
    """

    clamped = max(1, min(days, 365))
    return clamped * _NS_PER_DAY


def audit_timeline_from_traces(
    conn: sqlite3.Connection,
    *,
    limit: int,
    policy: TraceRedactionPolicy,
    cursor: str | None = None,
    session_id: str | None = None,
    kind: str | None = None,
    ts_from_ns: int | None = None,
    ts_to_ns: int | None = None,
) -> dict[str, object]:
    """Return a chronological audit timeline from ``trace_events``.

    Args:
        conn (sqlite3.Connection): Open ``traces.db`` connection.
        limit (int): Clamped page size.
        policy (TraceRedactionPolicy): Redaction policy applied on read.
        cursor (str | None): Previous page cursor (``ts_start_ns``).
        session_id (str | None): Optional session filter.
        kind (str | None): Optional exact kind filter.
        ts_from_ns (int | None): Inclusive lower bound on ``ts_start_ns``.
        ts_to_ns (int | None): Inclusive upper bound on ``ts_start_ns``.

    Returns:
        dict[str, object]: Cursor page of audit events.

    Examples:
        >>> import sqlite3
        >>> from sevn.agent.tracing.traces_migrate import apply_traces_migrations
        >>> from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_traces_migrations(conn)
        >>> policy = TraceRedactionPolicy.from_defaults()
        >>> audit_timeline_from_traces(conn, limit=5, policy=policy)["items"]
        []
        >>> conn.close()
    """

    return list_trace_events(
        conn,
        limit=limit,
        policy=policy,
        cursor=cursor,
        session_id=session_id,
        kind=kind,
        kind_prefixes=None if kind else list(_AUDIT_KIND_PREFIXES),
        ts_from_ns=ts_from_ns,
        ts_to_ns=ts_to_ns,
    )


def tool_frequency_from_traces(
    conn: sqlite3.Connection,
    *,
    days: int = 30,
) -> dict[str, object]:
    """Aggregate tool-call frequency by tool name for recent ``tool.*`` spans.

    Args:
        conn (sqlite3.Connection): Open ``traces.db`` connection.
        days (int): Lookback window in days.

    Returns:
        dict[str, object]: ``tools`` list with ``name`` and ``count``.

    Examples:
        >>> import sqlite3
        >>> from sevn.agent.tracing.traces_migrate import apply_traces_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_traces_migrations(conn)
        >>> tool_frequency_from_traces(conn, days=7)["tools"]
        []
        >>> conn.close()
    """

    cutoff_ns = time.time_ns() - _days_to_ns(days)
    rows = conn.execute(
        """
        SELECT COALESCE(NULLIF(json_extract(attrs_json, '$.name'), ''), kind) AS tool_name,
               COUNT(*) AS cnt
        FROM trace_events
        WHERE kind LIKE 'tool.%' AND ts_start_ns >= ?
        GROUP BY tool_name
        ORDER BY cnt DESC
        LIMIT 100
        """,
        (cutoff_ns,),
    ).fetchall()
    tools = [{"name": str(row[0]), "count": int(row[1])} for row in rows if row[0]]
    return {"tools": tools, "days": max(1, min(days, 365))}


def daily_volume_from_traces(
    conn: sqlite3.Connection,
    *,
    days: int = 30,
) -> dict[str, object]:
    """Return daily event volume aggregated from ``trace_rollups_hourly``.

    Args:
        conn (sqlite3.Connection): Open ``traces.db`` connection.
        days (int): Lookback window in days.

    Returns:
        dict[str, object]: ``days`` list with ``day_start_ns`` and ``event_count``.

    Examples:
        >>> import sqlite3
        >>> from sevn.agent.tracing.traces_migrate import apply_traces_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_traces_migrations(conn)
        >>> daily_volume_from_traces(conn, days=7)["days"]
        []
        >>> conn.close()
    """

    cutoff_ns = time.time_ns() - _days_to_ns(days)
    rows = conn.execute(
        """
        SELECT (hour_bucket_ns / ?) * ? AS day_bucket_ns,
               SUM(event_count) AS total_events
        FROM trace_rollups_hourly
        WHERE hour_bucket_ns >= ?
        GROUP BY day_bucket_ns
        ORDER BY day_bucket_ns ASC
        """,
        (_NS_PER_DAY, _NS_PER_DAY, cutoff_ns),
    ).fetchall()
    return {
        "days": [{"day_start_ns": int(row[0]), "event_count": int(row[1])} for row in rows],
        "window_days": max(1, min(days, 365)),
    }


def approval_timeline_from_traces(
    conn: sqlite3.Connection,
    *,
    limit: int,
    policy: TraceRedactionPolicy,
    cursor: str | None = None,
) -> dict[str, object]:
    """Return mission approval audit rows (``mission.approval.*`` kinds).

    Args:
        conn (sqlite3.Connection): Open ``traces.db`` connection.
        limit (int): Clamped page size.
        policy (TraceRedactionPolicy): Redaction policy applied on read.
        cursor (str | None): Previous page cursor (``ts_start_ns``).

    Returns:
        dict[str, object]: Cursor page of approval events.

    Examples:
        >>> import sqlite3
        >>> from sevn.agent.tracing.traces_migrate import apply_traces_migrations
        >>> from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_traces_migrations(conn)
        >>> policy = TraceRedactionPolicy.from_defaults()
        >>> approval_timeline_from_traces(conn, limit=5, policy=policy)["items"]
        []
        >>> conn.close()
    """

    return list_trace_events(
        conn,
        limit=limit,
        policy=policy,
        cursor=cursor,
        kind_prefixes=["mission.approval."],
    )


__all__ = [
    "approval_timeline_from_traces",
    "audit_timeline_from_traces",
    "daily_volume_from_traces",
    "tool_frequency_from_traces",
]
