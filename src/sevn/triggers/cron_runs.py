"""Persisted cron execution audit history (#85; ``specs/30-non-interactive-triggers.md``).

Module: sevn.triggers.cron_runs
Depends: sqlite3, time
Exports:
    cron_has_in_flight_run — whether a job has an incomplete audit row.
    cron_run_to_dict — dashboard-safe projection of one audit row.
    insert_cron_run_event — append one audit row for claim or completion.
    list_recent_cron_runs — recent rows for dashboard / ops APIs.
    recover_stale_cron_claims — mark in-flight rows stale at gateway boot.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

_IN_FLIGHT_STATUSES: frozenset[str] = frozenset({"claimed", "running"})
_STALE_ERROR = "gateway_restart_before_completion"


def insert_cron_run_event(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    run_id: str,
    claimed_at: int,
    status: str,
    completed_at: int | None = None,
    transcript_path: str | None = None,
    result_summary: str | None = None,
    error: str | None = None,
) -> None:
    """Insert one append-only row into ``cron_runs``.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        job_id (str): ``trigger_cron_jobs.job_id``.
        run_id (str): Stable id for this execution attempt.
        claimed_at (int): Claim instant in nanoseconds since epoch.
        status (str): Audit status label for this event row.
        completed_at (int | None, optional): Completion instant when known.
        transcript_path (str | None, optional): Workspace-relative transcript path.
        result_summary (str | None, optional): Short operator-facing summary.
        error (str | None, optional): Concise error text on failure.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.triggers.cron_runs import insert_cron_run_event
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> insert_cron_run_event(
        ...     c, job_id="j", run_id="r", claimed_at=1, status="running",
        ... )
        >>> c.execute("SELECT COUNT(*) FROM cron_runs").fetchone()[0]
        1
    """
    conn.execute(
        """
        INSERT INTO cron_runs (
            job_id, run_id, claimed_at, completed_at, status,
            transcript_path, result_summary, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            run_id,
            int(claimed_at),
            completed_at,
            status,
            transcript_path,
            result_summary,
            error,
        ),
    )
    conn.commit()


def cron_has_in_flight_run(conn: sqlite3.Connection, job_id: str) -> bool:
    """Return whether ``job_id`` has an incomplete cron audit row.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        job_id (str): Cron job primary key.

    Returns:
        bool: ``True`` when a claimed/running row lacks ``completed_at``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.triggers.cron_runs import cron_has_in_flight_run, insert_cron_run_event
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> cron_has_in_flight_run(c, "j")
        False
        >>> insert_cron_run_event(
        ...     c, job_id="j", run_id="r", claimed_at=1, status="running",
        ... )
        >>> cron_has_in_flight_run(c, "j")
        True
    """
    row = conn.execute(
        """
        SELECT 1 FROM cron_runs
        WHERE job_id = ?
          AND completed_at IS NULL
          AND status IN ('claimed', 'running')
        LIMIT 1
        """,
        (job_id,),
    ).fetchone()
    return row is not None


def recover_stale_cron_claims(conn: sqlite3.Connection, *, now_ns: int | None = None) -> int:
    """Mark in-flight cron audit rows stale after gateway restart.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        now_ns (int | None, optional): Reference instant; defaults to ``time.time_ns()``.

    Returns:
        int: Number of rows reconciled.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.triggers.cron_runs import insert_cron_run_event, recover_stale_cron_claims
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> insert_cron_run_event(
        ...     c, job_id="j", run_id="r", claimed_at=1, status="running",
        ... )
        >>> recover_stale_cron_claims(c, now_ns=2) >= 1
        True
    """
    ts = int(now_ns if now_ns is not None else time.time_ns())
    cur = conn.execute(
        """
        UPDATE cron_runs
        SET status = 'stale',
            completed_at = ?,
            error = ?
        WHERE completed_at IS NULL
          AND status IN ('claimed', 'running')
        """,
        (ts, _STALE_ERROR),
    )
    conn.commit()
    return int(cur.rowcount)


def list_recent_cron_runs(
    conn: sqlite3.Connection,
    *,
    limit: int = 50,
    job_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return recent cron audit rows for operator surfaces.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        limit (int): Maximum rows to return.
        job_id (str | None, optional): Filter to one job when set.

    Returns:
        list[dict[str, Any]]: Newest-first audit projections.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.triggers.cron_runs import list_recent_cron_runs
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> list_recent_cron_runs(c)
        []
    """
    cap = max(1, min(int(limit), 200))
    if job_id is not None:
        cur = conn.execute(
            """
            SELECT job_id, run_id, claimed_at, completed_at, status,
                   transcript_path, result_summary, error
            FROM cron_runs
            WHERE job_id = ?
            ORDER BY claimed_at DESC, rowid DESC
            LIMIT ?
            """,
            (job_id, cap),
        )
    else:
        cur = conn.execute(
            """
            SELECT job_id, run_id, claimed_at, completed_at, status,
                   transcript_path, result_summary, error
            FROM cron_runs
            ORDER BY claimed_at DESC, rowid DESC
            LIMIT ?
            """,
            (cap,),
        )
    return [
        {
            "job_id": str(r[0]),
            "run_id": str(r[1]),
            "claimed_at_ns": int(r[2]),
            "completed_at_ns": int(r[3]) if r[3] is not None else None,
            "status": str(r[4]),
            "transcript_path": str(r[5]) if r[5] is not None else None,
            "result_summary": str(r[6]) if r[6] is not None else None,
            "error": str(r[7]) if r[7] is not None else None,
        }
        for r in cur.fetchall()
    ]


def cron_run_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Return a dashboard-safe projection of one audit row.

    Args:
        row (dict[str, Any]): Row from :func:`list_recent_cron_runs`.

    Returns:
        dict[str, Any]: Same keys with ``error`` truncated for UI lists.

    Examples:
        >>> from sevn.triggers.cron_runs import cron_run_to_dict
        >>> cron_run_to_dict({"job_id": "j", "run_id": "r", "error": "x" * 500})["error"]
        'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
    """
    out = dict(row)
    err = out.get("error")
    if isinstance(err, str) and len(err) > 200:
        out["error"] = err[:200]
    return out


__all__ = [
    "cron_has_in_flight_run",
    "cron_run_to_dict",
    "insert_cron_run_event",
    "list_recent_cron_runs",
    "recover_stale_cron_claims",
]
