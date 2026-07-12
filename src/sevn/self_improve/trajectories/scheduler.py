"""Cron registration and watermark for trajectory ingest backfill.

Module: sevn.self_improve.trajectories.scheduler
Depends: sqlite3, time, sevn.config.workspace_config, sevn.triggers.cron

Exports:
    effective_trajectories — resolve typed trajectories block with defaults.
    reconcile_trajectory_ingest_cron_job — mirror config into SQLite.
    read_last_trajectory_ingest_ts_ns — load cron watermark from ``sevn.db``.
    write_last_trajectory_ingest_ts_ns — persist cron watermark in ``sevn.db``.
    run_scheduled_trajectory_ingest — incremental backfill for cron dispatch.
"""

from __future__ import annotations

import sqlite3  # noqa: TC003 — runtime cron reconcile and watermark IO
import time
from pathlib import Path  # noqa: TC003 — runtime trace path resolution
from typing import Final

from loguru import logger

from sevn.config.sections.self_improve import SelfImproveTrajectoriesWorkspaceConfig
from sevn.config.workspace_config import WorkspaceConfig  # noqa: TC001 — runtime cron reconcile
from sevn.self_improve.trajectories.runner import run_trajectory_ingest
from sevn.storage.paths import traces_sqlite_path
from sevn.triggers.cron import compute_next_fire_ns
from sevn.ui.dashboard.query.traces import ensure_trace_connection
from sevn.workspace.layout import WorkspaceLayout  # noqa: TC001 — cron dispatch layout arg

TRAJECTORY_INGEST_CRON_JOB_ID: Final[str] = "sevn_self_improve_trajectory_ingest"
_WATERMARK_SESSION_ID: Final[str] = "__trajectory_ingest__"
_WATERMARK_KEY: Final[str] = "last_trajectory_ingest_ts_ns"


def effective_trajectories(ws: WorkspaceConfig) -> SelfImproveTrajectoriesWorkspaceConfig:
    """Return ``SelfImproveTrajectoriesWorkspaceConfig`` with defaults when absent.

    Args:
        ws (WorkspaceConfig): Parsed workspace root model.

    Returns:
        SelfImproveTrajectoriesWorkspaceConfig: Effective trajectories config.

    Examples:
        >>> import sqlite3
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> effective_trajectories(WorkspaceConfig.minimal()).ingest_on_turn
        True
    """
    block = ws.self_improve
    if block is not None and block.trajectories is not None:
        return block.trajectories
    return SelfImproveTrajectoriesWorkspaceConfig()


def read_last_trajectory_ingest_ts_ns(conn: sqlite3.Connection) -> int | None:
    """Load the cron backfill watermark from ``sevn.db``.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` connection.

    Returns:
        int | None: Last ingested ``ts_start_ns`` when stored.

    Examples:
        >>> read_last_trajectory_ingest_ts_ns.__name__
        'read_last_trajectory_ingest_ts_ns'
    """
    row = conn.execute(
        """SELECT content FROM memory
           WHERE session_id = ? AND key = ?
           ORDER BY id DESC LIMIT 1""",
        (_WATERMARK_SESSION_ID, _WATERMARK_KEY),
    ).fetchone()
    if row is None:
        return None
    try:
        return int(str(row[0]))
    except ValueError:
        return None


def write_last_trajectory_ingest_ts_ns(conn: sqlite3.Connection, ts_ns: int) -> None:
    """Persist the cron backfill watermark in ``sevn.db``.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` connection.
        ts_ns (int): Latest processed ``trace_events.ts_start_ns``.

    Returns:
        None: Commits the watermark row.

    Examples:
        >>> write_last_trajectory_ingest_ts_ns.__name__
        'write_last_trajectory_ingest_ts_ns'
    """
    from datetime import UTC, datetime

    conn.execute(
        """INSERT INTO memory (key, session_id, content, created_at)
           VALUES (?, ?, ?, ?)""",
        (_WATERMARK_KEY, _WATERMARK_SESSION_ID, str(int(ts_ns)), datetime.now(tz=UTC).isoformat()),
    )
    conn.commit()


def _max_trace_ts_since(traces_db_path: Path, since_ns: int | None) -> int | None:
    """Return the max ``ts_start_ns`` for ingested tool/triage spans.

    Args:
        traces_db_path (Path): Path to ``traces.db``.
        since_ns (int | None): Optional lower bound.

    Returns:
        int | None: Max timestamp when any spans exist.

    Examples:
        >>> _max_trace_ts_since.__name__
        '_max_trace_ts_since'
    """
    path = traces_db_path
    trace_conn = ensure_trace_connection(path)
    try:
        sql = "SELECT MAX(ts_start_ns) FROM trace_events WHERE kind LIKE 'tool.%' OR kind = 'triage.complete'"
        params: tuple[object, ...] = ()
        if since_ns is not None:
            sql += " AND ts_start_ns >= ?"
            params = (since_ns,)
        row = trace_conn.execute(sql, params).fetchone()
    finally:
        trace_conn.close()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def reconcile_trajectory_ingest_cron_job(conn: sqlite3.Connection, ws: WorkspaceConfig) -> None:
    """Insert/update/delete the trajectory ingest cron row.

    Args:
        conn (sqlite3.Connection): Shared ``sevn.db`` connection (commits internally).
        ws (WorkspaceConfig): Workspace configuration source.

    Examples:
        >>> import sqlite3
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> reconcile_trajectory_ingest_cron_job(c, WorkspaceConfig.minimal())
        >>> int(c.execute("SELECT COUNT(*) FROM trigger_cron_jobs").fetchone()[0])
        1
        >>> c.close()
    """
    cfg = effective_trajectories(ws)
    job_id = TRAJECTORY_INGEST_CRON_JOB_ID
    cron_expr = cfg.ingest_cron.strip()
    if not cron_expr:
        conn.execute("DELETE FROM trigger_cron_jobs WHERE job_id = ?", (job_id,))
        conn.commit()
        return
    now_ns = time.time_ns()
    nxt = compute_next_fire_ns(cron_expr=cron_expr, tz_name="UTC", from_ns=now_ns)
    conn.execute(
        """
        INSERT INTO trigger_cron_jobs (
            job_id, enabled, cron_expr, timezone, next_fire_at_ns, jitter_s,
            routing_mode, delivery_mode, permission_template_ref, allow_tier_cd,
            overlap_policy, result_channel_json, payload_template
        ) VALUES (?, 1, ?, 'UTC', ?, 0, 'fixed', 'notify_only', 'default', 0, 'skip', '{}', ?)
        ON CONFLICT(job_id) DO UPDATE SET
            enabled = excluded.enabled,
            cron_expr = excluded.cron_expr,
            timezone = excluded.timezone,
            next_fire_at_ns = excluded.next_fire_at_ns,
            routing_mode = excluded.routing_mode,
            delivery_mode = excluded.delivery_mode,
            permission_template_ref = excluded.permission_template_ref,
            allow_tier_cd = excluded.allow_tier_cd,
            overlap_policy = excluded.overlap_policy,
            result_channel_json = excluded.result_channel_json,
            payload_template = excluded.payload_template
        """,
        (job_id, cron_expr, int(nxt), "sevn_self_improve_trajectory_ingest"),
    )
    conn.commit()


def run_scheduled_trajectory_ingest(
    conn: sqlite3.Connection,
    layout: WorkspaceLayout,
    ws: WorkspaceConfig,
) -> None:
    """Run incremental trajectory ingest for the nightly cron backfill.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` connection.
        layout (WorkspaceLayout): Workspace layout for trace path resolution.
        ws (WorkspaceConfig): Parsed workspace config (unused except for symmetry).

    Returns:
        None: Side-effect only.

    Examples:
        >>> run_scheduled_trajectory_ingest.__name__
        'run_scheduled_trajectory_ingest'
    """
    _ = ws
    traces_path = traces_sqlite_path(layout.dot_sevn)
    if not traces_path.is_file():
        return
    since_ns = read_last_trajectory_ingest_ts_ns(conn)
    result = run_trajectory_ingest(conn, layout, since_ns=since_ns)
    if result is None:
        return
    max_ts = _max_trace_ts_since(traces_path, since_ns=since_ns)
    if max_ts is not None:
        write_last_trajectory_ingest_ts_ns(conn, max_ts)
    logger.debug(
        "trajectory_ingest_cron rows_upserted={} since_ns={}",
        result.rows_upserted,
        since_ns,
    )


__all__ = [
    "TRAJECTORY_INGEST_CRON_JOB_ID",
    "effective_trajectories",
    "read_last_trajectory_ingest_ts_ns",
    "reconcile_trajectory_ingest_cron_job",
    "run_scheduled_trajectory_ingest",
    "write_last_trajectory_ingest_ts_ns",
]
