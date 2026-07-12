"""SQLite persistence for ``self_improve_jobs`` (`specs/33-self-improvement.md` §3.3).

Module: sevn.self_improve.jobs.store
Depends: dataclasses, datetime, json, sqlite3, uuid

Exports:
    ImproveJobRow — hydrated job row for worker processing.
    abort_job_row — operator-only abort transition.
    claim_next_queued_job — atomic queued → running claim.
    enqueue_job_row — insert or return existing job for dedupe tokens.
    fetch_job_row — load one job row by id.
    list_recent_job_rows — newest jobs for dashboard browse.
    requeue_after_plan_approval — resume jobs after spec-kit plan HITL.
    update_job_state — lifecycle transition helper with optional artefact paths.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sevn.self_improve.types import ImproveJobId

if TYPE_CHECKING:
    import sqlite3

    from sevn.self_improve.jobs.events import ImproveJobState


@dataclass(frozen=True, slots=True)
class ImproveJobRow:
    """Hydrated ``self_improve_jobs`` row for worker processing."""

    job_id: str
    workspace_id: str
    state: ImproveJobState
    preset: str
    sampler_seed: int
    correlation_id: str | None
    shortlist_path: str | None
    eval_report_path: str | None
    blocked_reason: str | None


def _row_from_sql(row: tuple[object, ...]) -> ImproveJobRow:
    """Map a SELECT tuple into :class:`ImproveJobRow`.

    Args:
        row (tuple[object, ...]): Column tuple from ``self_improve_jobs``.

    Returns:
        ImproveJobRow: Typed view for worker stages.

    Examples:
        >>> _row_from_sql(
        ...     ("j", "w", "queued", "A", 1, None, None, None, None),
        ... ).preset
        'A'
    """
    return ImproveJobRow(
        job_id=str(row[0]),
        workspace_id=str(row[1]),
        state=str(row[2]),  # type: ignore[arg-type]
        preset=str(row[3]),
        sampler_seed=int(str(row[4])),
        correlation_id=str(row[5]) if row[5] is not None else None,
        shortlist_path=str(row[6]) if row[6] is not None else None,
        eval_report_path=str(row[7]) if row[7] is not None else None,
        blocked_reason=str(row[8]) if row[8] is not None else None,
    )


_JOB_SELECT = """SELECT job_id, workspace_id, state, preset, sampler_seed,
    correlation_id, shortlist_path, eval_report_path, blocked_reason
    FROM self_improve_jobs"""


def enqueue_job_row(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    experiment_id: str,
    preset: str,
    sampler_seed: int,
    correlation_id: str | None,
    client_token: str | None,
    experiment_snapshot: dict[str, object],
) -> ImproveJobId:
    """Insert a queued job row, or return the prior id for the same dedupe key.

    Args:
    conn (sqlite3.Connection): Open ``sevn.db`` connection with migrations applied.
    workspace_id (str): Owning workspace scope.
    experiment_id (str): Active experiment identifier.
    preset (str): ``A``, ``B``, or ``C``.
    sampler_seed (int): Deterministic seed for allocator outputs.
    correlation_id (str | None): Optional upstream stitch id.
    client_token (str | None): Idempotency token (``UNIQUE(workspace_id, client_token)``).
    experiment_snapshot (dict[str, object]): Serialisable config slice + ``experiment_id``.

    Returns:
        ImproveJobId: New or existing primary key.

    Raises:
        sqlite3.IntegrityError: When a non-null client collides outside the dedupe tuple.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> t = "tok"
        >>> j1 = enqueue_job_row(
        ...     conn,
        ...     workspace_id="w",
        ...     experiment_id="e",
        ...     preset="A",
        ...     sampler_seed=1,
        ...     correlation_id=None,
        ...     client_token=t,
        ...     experiment_snapshot={"experiment_id": "e"},
        ... )
        >>> j2 = enqueue_job_row(
        ...     conn,
        ...     workspace_id="w",
        ...     experiment_id="e",
        ...     preset="A",
        ...     sampler_seed=1,
        ...     correlation_id=None,
        ...     client_token=t,
        ...     experiment_snapshot={"experiment_id": "e"},
        ... )
        >>> j1 == j2
        True
        >>> conn.close()
    """
    if client_token:
        row = conn.execute(
            "SELECT job_id FROM self_improve_jobs WHERE workspace_id = ? AND client_token = ?",
            (workspace_id, client_token),
        ).fetchone()
        if row is not None:
            return ImproveJobId(str(row[0]))

    job_id = ImproveJobId(uuid.uuid4().hex)
    started_at = datetime.now(tz=UTC).isoformat()
    snap = dict(experiment_snapshot)
    snap.setdefault("experiment_id", experiment_id)
    payload = json.dumps(snap, sort_keys=True)

    conn.execute(
        """INSERT INTO self_improve_jobs (
            job_id,
            workspace_id,
            state,
            preset,
            experiment_snapshot_json,
            sampler_seed,
            correlation_id,
            client_token,
            shortlist_path,
            started_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
        (
            job_id,
            workspace_id,
            "queued",
            preset,
            payload,
            sampler_seed,
            correlation_id,
            client_token,
            started_at,
        ),
    )
    conn.commit()
    return job_id


def abort_job_row(conn: sqlite3.Connection, *, job_id: ImproveJobId) -> bool:
    """Mark ``aborted`` when the row exists.

    Args:
    conn (sqlite3.Connection): Open ``sevn.db`` connection with migrations applied.
    job_id (ImproveJobId): Target id.

    Returns:
        bool: True when a row was updated.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.self_improve.types import ImproveJobId
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> jid = enqueue_job_row(
        ...     conn,
        ...     workspace_id="w",
        ...     experiment_id="e",
        ...     preset="A",
        ...     sampler_seed=1,
        ...     correlation_id=None,
        ...     client_token=None,
        ...     experiment_snapshot={},
        ... )
        >>> abort_job_row(conn, job_id=jid)
        True
        >>> abort_job_row(conn, job_id=ImproveJobId("missing"))
        False
        >>> conn.close()
    """
    finished_at = datetime.now(tz=UTC).isoformat()
    cur = conn.execute(
        """UPDATE self_improve_jobs SET state = 'aborted', finished_at = ?
            WHERE job_id = ?""",
        (finished_at, job_id),
    )
    conn.commit()
    return cur.rowcount > 0


def fetch_job_row(conn: sqlite3.Connection, *, job_id: ImproveJobId) -> ImproveJobRow | None:
    """Load one improve job row by primary key.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` connection with migrations applied.
        job_id (ImproveJobId): Target id.

    Returns:
        ImproveJobRow | None: Row when present.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.self_improve.types import ImproveJobId
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> jid = enqueue_job_row(
        ...     conn,
        ...     workspace_id="w",
        ...     experiment_id="e",
        ...     preset="A",
        ...     sampler_seed=1,
        ...     correlation_id=None,
        ...     client_token=None,
        ...     experiment_snapshot={},
        ... )
        >>> fetch_job_row(conn, job_id=jid) is not None
        True
        >>> conn.close()
    """
    row = conn.execute(f"{_JOB_SELECT} WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return _row_from_sql(row)


def list_recent_job_rows(
    conn: sqlite3.Connection,
    *,
    workspace_id: str | None = None,
    limit: int = 50,
) -> list[ImproveJobRow]:
    """Return recent improve jobs ordered by ``started_at`` desc.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` connection with migrations applied.
        workspace_id (str | None): Optional workspace filter; ``None`` lists all rows.
        limit (int): Maximum rows to return.

    Returns:
        list[ImproveJobRow]: Newest jobs first.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> _ = enqueue_job_row(
        ...     conn,
        ...     workspace_id="w",
        ...     experiment_id="e",
        ...     preset="A",
        ...     sampler_seed=1,
        ...     correlation_id=None,
        ...     client_token=None,
        ...     experiment_snapshot={},
        ... )
        >>> len(list_recent_job_rows(conn))
        1
        >>> conn.close()
    """
    if workspace_id is None:
        rows = conn.execute(
            f"""{_JOB_SELECT}
                ORDER BY started_at DESC
                LIMIT ?""",
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            f"""{_JOB_SELECT}
                WHERE workspace_id = ?
                ORDER BY started_at DESC
                LIMIT ?""",
            (workspace_id, limit),
        ).fetchall()
    return [_row_from_sql(row) for row in rows]


def claim_next_queued_job(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
) -> ImproveJobRow | None:
    """Atomically claim the oldest queued job for one workspace.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` connection with migrations applied.
        workspace_id (str): Owning workspace scope.

    Returns:
        ImproveJobRow | None: Claimed row in ``running`` state, or ``None`` when idle.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> jid = enqueue_job_row(
        ...     conn,
        ...     workspace_id="w",
        ...     experiment_id="e",
        ...     preset="A",
        ...     sampler_seed=1,
        ...     correlation_id=None,
        ...     client_token=None,
        ...     experiment_snapshot={},
        ... )
        >>> claimed = claim_next_queued_job(conn, workspace_id="w")
        >>> claimed is not None and claimed.job_id == jid and claimed.state == "running"
        True
        >>> conn.close()
    """
    row = conn.execute(
        f"""{_JOB_SELECT}
            WHERE workspace_id = ? AND state = 'queued'
            ORDER BY started_at ASC
            LIMIT 1""",
        (workspace_id,),
    ).fetchone()
    if row is None:
        return None
    job_id = ImproveJobId(str(row[0]))
    cur = conn.execute(
        """UPDATE self_improve_jobs SET state = 'running'
            WHERE job_id = ? AND state = 'queued'""",
        (job_id,),
    )
    if cur.rowcount == 0:
        conn.commit()
        return None
    conn.commit()
    refreshed = conn.execute(f"{_JOB_SELECT} WHERE job_id = ?", (job_id,)).fetchone()
    if refreshed is None:
        return None
    claimed = _row_from_sql(refreshed)
    return ImproveJobRow(
        job_id=claimed.job_id,
        workspace_id=claimed.workspace_id,
        state="running",
        preset=claimed.preset,
        sampler_seed=claimed.sampler_seed,
        correlation_id=claimed.correlation_id,
        shortlist_path=claimed.shortlist_path,
        eval_report_path=claimed.eval_report_path,
        blocked_reason=claimed.blocked_reason,
    )


def requeue_after_plan_approval(
    conn: sqlite3.Connection,
    *,
    job_id: ImproveJobId,
) -> bool:
    """Move a job from ``awaiting_plan_review`` back to ``queued`` for worker resume.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` connection.
        job_id (ImproveJobId): Target job id.

    Returns:
        bool: ``True`` when a row was updated.

    Examples:
        >>> requeue_after_plan_approval.__name__
        'requeue_after_plan_approval'
    """
    cur = conn.execute(
        """UPDATE self_improve_jobs
            SET state = 'queued', blocked_reason = NULL
            WHERE job_id = ? AND state = 'awaiting_plan_review'""",
        (job_id,),
    )
    conn.commit()
    return cur.rowcount > 0


def update_job_state(
    conn: sqlite3.Connection,
    *,
    job_id: ImproveJobId,
    state: str,
    shortlist_path: str | None = None,
    eval_report_path: str | None = None,
    blocked_reason: str | None = None,
) -> bool:
    """Transition one job row and optionally persist artefact paths.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` connection with migrations applied.
        job_id (ImproveJobId): Target id.
        state (ImproveJobState): Destination lifecycle state.
        shortlist_path (str | None): Optional shortlist artefact path.
        eval_report_path (str | None): Optional eval report path after eval completes.
        blocked_reason (str | None): Optional blocked reason when ``state='blocked'``.

    Returns:
        bool: ``True`` when a row was updated.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.self_improve.types import ImproveJobId
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> jid = enqueue_job_row(
        ...     conn,
        ...     workspace_id="w",
        ...     experiment_id="e",
        ...     preset="A",
        ...     sampler_seed=1,
        ...     correlation_id=None,
        ...     client_token=None,
        ...     experiment_snapshot={},
        ... )
        >>> update_job_state(
        ...     conn,
        ...     job_id=jid,
        ...     state="awaiting_review",
        ...     eval_report_path="/tmp/eval_report.json",
        ... )
        True
        >>> row = fetch_job_row(conn, job_id=jid)
        >>> row is not None and row.state == "awaiting_review"
        True
        >>> conn.close()
    """
    sets = ["state = ?"]
    params: list[object] = [state]
    if shortlist_path is not None:
        sets.append("shortlist_path = ?")
        params.append(shortlist_path)
    if eval_report_path is not None:
        sets.append("eval_report_path = ?")
        params.append(eval_report_path)
    if blocked_reason is not None:
        sets.append("blocked_reason = ?")
        params.append(blocked_reason)
    if state in ("blocked", "merged", "aborted"):
        finished_at = datetime.now(tz=UTC).isoformat()
        sets.append("finished_at = ?")
        params.append(finished_at)
    params.append(job_id)
    cur = conn.execute(
        f"UPDATE self_improve_jobs SET {', '.join(sets)} WHERE job_id = ?",  # nosec B608 — sets are fixed column assignments
        params,
    )
    conn.commit()
    return cur.rowcount > 0
