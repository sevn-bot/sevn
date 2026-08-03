"""Durable trigger run status rows in ``sevn.db`` (#147).

Module: sevn.storage.trigger_runs

Replaces the process-local ``app.state.trigger_run_status`` dict for
``GET /api/v1/runs/{run_id}`` so a restarted gateway still reports runs it
accepted before the restart.

Exports:
    get_trigger_run_status — read one run's coarse status label.
    upsert_trigger_run_status — insert or update a run row.

Examples:
    >>> import sqlite3
    >>> from sevn.storage.migrate import apply_migrations
    >>> from sevn.storage.trigger_runs import get_trigger_run_status, upsert_trigger_run_status
    >>> conn = sqlite3.connect(":memory:")
    >>> apply_migrations(conn)
    >>> upsert_trigger_run_status(
    ...     conn, run_id="r1", correlation_id="r1", status="completed",
    ...     now="2026-08-03T00:00:00Z",
    ... )
    >>> get_trigger_run_status(conn, "r1")
    'completed'
    >>> conn.close()
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime


def _utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 ``Z`` form.

    Returns:
        str: Timestamp like ``2026-08-03T00:00:00Z``.

    Examples:
        >>> _utc_now_iso().endswith("Z")
        True
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def upsert_trigger_run_status(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    correlation_id: str,
    status: str,
    now: str | None = None,
) -> None:
    """Insert or update one ``trigger_runs`` row.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle at migration head.
        run_id (str): Primary run identifier (unique).
        correlation_id (str): Caller correlation id (usually matches ``run_id``).
        status (str): Coarse status label (``accepted``, ``completed``, …).
        now (str | None): ISO-8601 UTC timestamp; defaults to current time.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> upsert_trigger_run_status(
        ...     conn, run_id="x", correlation_id="x", status="accepted", now="t0",
        ... )
        >>> upsert_trigger_run_status(
        ...     conn, run_id="x", correlation_id="x", status="completed", now="t1",
        ... )
        >>> get_trigger_run_status(conn, "x")
        'completed'
        >>> conn.close()
    """
    ts = now or _utc_now_iso()
    conn.execute(
        """
        INSERT INTO trigger_runs (run_id, correlation_id, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            status = excluded.status,
            updated_at = excluded.updated_at
        """,
        (run_id, correlation_id, status, ts, ts),
    )
    conn.commit()


def get_trigger_run_status(conn: sqlite3.Connection, run_id: str) -> str | None:
    """Return the persisted status for ``run_id``, or ``None`` when absent.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        run_id (str): Run identifier from ``POST /api/v1/run``.

    Returns:
        str | None: Stored status label, or ``None`` when no row exists.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> get_trigger_run_status(conn, "missing") is None
        True
        >>> conn.close()
    """
    row = conn.execute(
        "SELECT status FROM trigger_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return str(row[0]) if row is not None else None


__all__ = ["get_trigger_run_status", "upsert_trigger_run_status"]
