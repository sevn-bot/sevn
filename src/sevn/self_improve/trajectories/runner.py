"""Orchestrate trajectory ingest from ``traces.db`` into ``sevn.db``.

Module: sevn.self_improve.trajectories.runner
Depends: sqlite3, loguru, sevn.self_improve.trajectories.ingest, sevn.storage.paths

Exports:
    run_trajectory_ingest — shared entry for worker, turn hook, and cron backfill.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from sevn.self_improve.trajectories.ingest import (
    TrajectoryIngestResult,
    ingest_trajectory_fact_for_turn,
    ingest_trajectory_facts_from_traces,
)
from sevn.storage.paths import traces_sqlite_path

if TYPE_CHECKING:
    import sqlite3

    from sevn.workspace.layout import WorkspaceLayout


def run_trajectory_ingest(
    sevn_conn: sqlite3.Connection,
    layout: WorkspaceLayout,
    *,
    turn_id: str | None = None,
    since_ns: int | None = None,
) -> TrajectoryIngestResult | None:
    """Ingest ``trajectory_fact`` rows when ``traces.db`` exists.

    Args:
        sevn_conn (sqlite3.Connection): Open ``sevn.db`` connection.
        layout (WorkspaceLayout): Workspace layout for ``traces.db`` path.
        turn_id (str | None): When set, ingest only this turn's spans.
        since_ns (int | None): Lower bound on ``trace_events.ts_start_ns``.

    Returns:
        TrajectoryIngestResult | None: Counters when ingest ran; ``None`` when
            ``traces.db`` is absent.

    Examples:
        >>> run_trajectory_ingest.__name__
        'run_trajectory_ingest'
    """
    traces_path = traces_sqlite_path(layout.dot_sevn)
    if not traces_path.is_file():
        return None
    if turn_id is not None:
        result = ingest_trajectory_fact_for_turn(sevn_conn, traces_path, turn_id=turn_id)
    else:
        result = ingest_trajectory_facts_from_traces(sevn_conn, traces_path, since_ns=since_ns)
    logger.debug(
        "trajectory_ingest rows_upserted={} turns_processed={} turn_id={} since_ns={}",
        result.rows_upserted,
        result.turns_processed,
        turn_id,
        since_ns,
    )
    return result


__all__ = ["run_trajectory_ingest"]
