"""TTL purge + hourly rollup writers for ``traces.db`` (`specs/04-tracing.md` §10.7).
Module: sevn.agent.tracing.traces_maintenance
Depends: logging, sqlite3, time, pathlib, sevn.config.defaults
Exports:
    purge_trace_events_ttl — delete rows older than ``ttl_days``.
    write_hourly_rollups — idempotent aggregate writer for the prior hours.
Examples:
    >>> from sevn.agent.tracing.traces_maintenance import HOUR_NS
    >>> HOUR_NS == 3600 * 1_000_000_000
    True
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from loguru import logger

from sevn.config.defaults import (
    DEFAULT_TRACE_ROLLUP_LOOKBACK_HOURS,
    DEFAULT_TRACE_TTL_DAYS,
)

HOUR_NS: int = 3600 * 1_000_000_000
_DAY_NS: int = 24 * HOUR_NS


def _hour_bucket_ns(ts_ns: int) -> int:
    """Floor ``ts_ns`` to its hour bucket boundary (UTC-naive ns).
    Args:
        ts_ns (int): Nanosecond timestamp.
    Returns:
        int: ``ts_ns - (ts_ns % HOUR_NS)``.
    Examples:
        >>> _hour_bucket_ns(HOUR_NS + 5) == HOUR_NS
        True
    """
    return ts_ns - (ts_ns % HOUR_NS)


def purge_trace_events_ttl(
    db_path: Path,
    *,
    ttl_days: int = DEFAULT_TRACE_TTL_DAYS,
    now_ns: int | None = None,
) -> int:
    """Delete ``trace_events`` rows whose ``ts_start_ns`` is older than ``ttl_days``.
    Mirrors the snapshot GC pattern (`specs/16-harness-discipline.md` §2.2 +
    ``HARNESS_SNAPSHOT_GC_ORPHAN_MAX_AGE_NS``): retention is wall-clock-bounded
    by ``ts_start_ns``. Returns the number of rows deleted; ``0`` when the
    database file does not exist yet (gateway boot ordering tolerance).
    Args:
        db_path (Path): ``traces.db`` location.
        ttl_days (int): Retention window; ``<= 0`` disables the purge.
        now_ns (int | None): Monotonic clock override (tests).
    Returns:
        int: Rows deleted (``0`` when disabled or db missing).
    Examples:
        >>> from pathlib import Path
        >>> purge_trace_events_ttl(Path("/no/such/db"), ttl_days=0) == 0
        True
    """
    if ttl_days <= 0:
        return 0
    if not db_path.exists():
        return 0
    cutoff_ns = int(now_ns if now_ns is not None else time.time_ns()) - ttl_days * _DAY_NS
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "DELETE FROM trace_events WHERE ts_start_ns < ?",
            (cutoff_ns,),
        )
        deleted = int(cur.rowcount or 0)
        # Drop rollups that fall entirely behind the retention boundary too.
        conn.execute(
            "DELETE FROM trace_rollups_hourly WHERE hour_bucket_ns + ? < ?",
            (HOUR_NS, cutoff_ns),
        )
        conn.commit()
    finally:
        conn.close()
    if deleted:
        logger.bind(db_path=str(db_path), deleted=deleted, ttl_days=ttl_days).info(
            "trace ttl purge deleted rows"
        )
    return deleted


def write_hourly_rollups(
    db_path: Path,
    *,
    lookback_hours: int = DEFAULT_TRACE_ROLLUP_LOOKBACK_HOURS,
    now_ns: int | None = None,
) -> int:
    """Recompute ``trace_rollups_hourly`` for the last ``lookback_hours`` buckets.
    Idempotent: re-running over the same window UPSERTs the row, so counts
    *replace* (never accumulate). Only buckets whose entire hour has elapsed
    are written — the current in-progress hour is skipped so partial data is
    never persisted as a "final" rollup.
    Args:
        db_path (Path): ``traces.db`` location.
        lookback_hours (int): Number of recently-closed hour buckets to recompute.
        now_ns (int | None): Monotonic clock override (tests).
    Returns:
        int: Number of ``(hour_bucket_ns, kind)`` rows upserted.
    Examples:
        >>> from pathlib import Path
        >>> write_hourly_rollups(Path("/no/such/db")) == 0
        True
    """
    if lookback_hours <= 0:
        return 0
    if not db_path.exists():
        return 0
    now = int(now_ns if now_ns is not None else time.time_ns())
    current_bucket = _hour_bucket_ns(now)
    # The "current" bucket is in-progress — start one hour back.
    upper_exclusive = current_bucket
    lower_inclusive = current_bucket - lookback_hours * HOUR_NS
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            """
            SELECT
                (ts_start_ns - (ts_start_ns % ?)) AS hour_bucket_ns,
                kind,
                COUNT(*) AS event_count,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error_count,
                AVG(CASE
                    WHEN ts_end_ns IS NOT NULL THEN ts_end_ns - ts_start_ns
                    ELSE NULL
                END) AS avg_duration_ns,
                MAX(CASE
                    WHEN ts_end_ns IS NOT NULL THEN ts_end_ns - ts_start_ns
                    ELSE NULL
                END) AS max_duration_ns
            FROM trace_events
            WHERE ts_start_ns >= ? AND ts_start_ns < ?
            GROUP BY hour_bucket_ns, kind
            """,
            (HOUR_NS, lower_inclusive, upper_exclusive),
        ).fetchall()
        written = 0
        for hour_bucket_ns, kind, event_count, error_count, avg_dur, max_dur in rows:
            conn.execute(
                """
                INSERT INTO trace_rollups_hourly (
                    hour_bucket_ns, kind, event_count, error_count,
                    avg_duration_ns, max_duration_ns, updated_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(hour_bucket_ns, kind) DO UPDATE SET
                    event_count = excluded.event_count,
                    error_count = excluded.error_count,
                    avg_duration_ns = excluded.avg_duration_ns,
                    max_duration_ns = excluded.max_duration_ns,
                    updated_at_ns = excluded.updated_at_ns
                """,
                (
                    int(hour_bucket_ns),
                    str(kind),
                    int(event_count),
                    int(error_count or 0),
                    float(avg_dur) if avg_dur is not None else None,
                    int(max_dur) if max_dur is not None else None,
                    now,
                ),
            )
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


__all__ = [
    "HOUR_NS",
    "purge_trace_events_ttl",
    "write_hourly_rollups",
]
