"""``subagent_runs`` persistence: write-through, boot orphan sweep, retention prune (D10).

Module: sevn.agent.subagents.storage
Depends: asyncio, sqlite3, time, loguru, sevn.agent.subagents.models,
    sevn.agent.subagents.registry

Exports:
    persist_subagent_run — upsert one row from a ``SubAgentRun`` (write-through).
    sqlite_persist_hook — build a :data:`PersistHook` bound to a connection.
    sweep_orphaned_subagent_runs — boot-time: mark stale rows ``orphaned``.
    prune_subagent_runs — retention: delete old terminal rows.
    list_recent_subagent_runs — recent terminal rows for Mission Control history.
    restore_pending_subagent_deliveries — boot replay of undelivered level-2 results.
    mark_subagent_result_delivered — record that a persisted result reached the channel.
    load_subagent_result_body — read persisted completion text for one run id.

Examples:
    >>> import sqlite3
    >>> from sevn.storage.migrate import apply_migrations
    >>> conn = sqlite3.connect(":memory:")
    >>> apply_migrations(conn)
    >>> int(conn.execute("SELECT COUNT(*) FROM subagent_runs").fetchone()[0])
    0
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import TYPE_CHECKING, cast

from loguru import logger

from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy, redact_text_value

if TYPE_CHECKING:
    from sevn.agent.subagents.registry import PersistHook
    from sevn.gateway.channel_router import ChannelRouter


def _commit_if_in_transaction(conn: sqlite3.Connection) -> None:
    """Commit only when an explicit transaction is open (skip autocommit no-ops).

    Args:
        conn (sqlite3.Connection): Open SQLite connection.

    Examples:
        >>> import sqlite3
        >>> conn = sqlite3.connect(":memory:", isolation_level=None)
        >>> _ = conn.execute("CREATE TABLE t(x)")
        >>> _commit_if_in_transaction(conn)
    """
    if conn.in_transaction:
        conn.commit()


def list_recent_subagent_runs(
    conn: sqlite3.Connection,
    *,
    limit: int = 30,
) -> list[dict[str, object]]:
    """Return recent terminal ``subagent_runs`` rows for Mission Control history (D10).

    Args:
        conn (sqlite3.Connection): Open, migrated ``sevn.db`` connection.
        limit (int): Maximum rows to return (newest first).

    Returns:
        list[dict[str, object]]: Serialized history rows.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> persist_subagent_run(conn, SubAgentRun(
        ...     id="a1f3", level=1, role="tier_b", specialist=None, parent_id=None,
        ...     session_id="s1", channel="telegram", task_summary="hi",
        ...     status=SubAgentStatus.DONE, started_at=1, finished_at=2,
        ...     trace_id=None,
        ... ))
        >>> rows = list_recent_subagent_runs(conn, limit=5)
        >>> rows[0]["id"]
        'a1f3'
    """
    safe_limit = max(1, min(int(limit), 200))
    placeholders = ",".join("?" * len(_TERMINAL_STATUSES))
    sql = f"""
        SELECT
            id, level, role, specialist, parent_id, session_id, channel,
            task_summary, status, started_at_ns, finished_at_ns, trace_id
        FROM subagent_runs
        WHERE status IN ({placeholders})
        ORDER BY COALESCE(finished_at_ns, started_at_ns) DESC
        LIMIT ?
    """  # nosec B608 — placeholders are bound status literals only
    cursor = conn.execute(sql, (*_TERMINAL_STATUSES, safe_limit))
    rows: list[dict[str, object]] = []
    for row in cursor.fetchall():
        rows.append(
            {
                "id": row[0],
                "level": int(row[1]),
                "role": row[2],
                "specialist": row[3],
                "parent_id": row[4],
                "session_id": row[5],
                "channel": row[6],
                "task_summary": row[7],
                "status": row[8],
                "started_at_ns": int(row[9]),
                "finished_at_ns": int(row[10]) if row[10] is not None else None,
                "trace_id": row[11],
            },
        )
    return rows


__all__ = [
    "list_recent_subagent_runs",
    "load_subagent_result_body",
    "mark_subagent_result_delivered",
    "persist_subagent_run",
    "prune_subagent_runs",
    "restore_pending_subagent_deliveries",
    "sqlite_persist_hook",
    "sweep_orphaned_subagent_runs",
]

_STALE_STATUSES: tuple[str, ...] = (SubAgentStatus.PENDING.value, SubAgentStatus.RUNNING.value)
_TERMINAL_STATUSES: tuple[str, ...] = (
    SubAgentStatus.DONE.value,
    SubAgentStatus.FAILED.value,
    SubAgentStatus.KILLED.value,
    SubAgentStatus.ORPHANED.value,
)


def persist_subagent_run(
    conn: sqlite3.Connection,
    run: SubAgentRun,
    *,
    result_body: str | None = None,
    transcript_path: str | None = None,
) -> None:
    """Upsert one ``subagent_runs`` row from a registry transition (D10 write-through).

    Args:
        conn (sqlite3.Connection): Open, migrated ``sevn.db`` connection.
        run (SubAgentRun): Current row state.
        result_body (str | None): Optional completion text for level-2 announce-back
            replay (#76). When ``None``, an existing stored body is preserved.
        transcript_path (str | None): Optional workspace-relative JSONL path (#77).
            When ``None``, an existing stored path is preserved.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> run = SubAgentRun(
        ...     id="a1f3", level=1, role="tier_b", specialist=None, parent_id=None,
        ...     session_id="s1", channel="telegram", task_summary="hi",
        ...     status=SubAgentStatus.PENDING, started_at=1, finished_at=None,
        ...     trace_id=None,
        ... )
        >>> persist_subagent_run(conn, run)
        >>> conn.execute("SELECT status FROM subagent_runs WHERE id = 'a1f3'").fetchone()[0]
        'pending'
    """
    stored_body = result_body
    if stored_body is not None:
        policy = TraceRedactionPolicy.from_defaults()
        stored_body = redact_text_value(stored_body, policy)
    try:
        conn.execute(
            """
            INSERT INTO subagent_runs (
                id, level, role, specialist, parent_id, session_id, channel,
                task_summary, status, started_at_ns, finished_at_ns, trace_id,
                result_body, transcript_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                level = excluded.level,
                role = excluded.role,
                specialist = excluded.specialist,
                parent_id = excluded.parent_id,
                session_id = excluded.session_id,
                channel = excluded.channel,
                task_summary = excluded.task_summary,
                status = excluded.status,
                started_at_ns = excluded.started_at_ns,
                finished_at_ns = excluded.finished_at_ns,
                trace_id = excluded.trace_id,
                result_body = COALESCE(excluded.result_body, subagent_runs.result_body),
                transcript_path = COALESCE(excluded.transcript_path, subagent_runs.transcript_path)
            """,
            (
                run.id,
                int(run.level),
                run.role,
                run.specialist,
                run.parent_id,
                run.session_id,
                run.channel,
                run.task_summary,
                run.status.value,
                int(run.started_at),
                run.finished_at,
                run.trace_id,
                stored_body,
                transcript_path,
            ),
        )
        _commit_if_in_transaction(conn)
    except sqlite3.Error:
        logger.bind(subagent_id=run.id, session_id=run.session_id).exception(
            "persist_subagent_run SQL failed"
        )
        raise


def sqlite_persist_hook(conn: sqlite3.Connection) -> PersistHook:
    """Build a :data:`PersistHook` that write-throughs to ``subagent_runs``.

    Wraps the blocking SQLite call in :func:`asyncio.to_thread` so the async
    registry never blocks the event loop (`coding-standards.md` async rules).

    Args:
        conn (sqlite3.Connection): Open, migrated ``sevn.db`` connection.

    Returns:
        PersistHook: Async callback suitable for ``SubAgentRegistry(persist=...)``.

    Examples:
        >>> import asyncio
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
        >>> conn = sqlite3.connect(":memory:", check_same_thread=False)
        >>> apply_migrations(conn)
        >>> hook = sqlite_persist_hook(conn)
        >>> run = SubAgentRun(
        ...     id="a1f3", level=1, role="tier_b", specialist=None, parent_id=None,
        ...     session_id="s1", channel="telegram", task_summary="hi",
        ...     status=SubAgentStatus.DONE, started_at=1, finished_at=2,
        ...     trace_id=None,
        ... )
        >>> asyncio.run(hook(run))
        >>> conn.execute("SELECT status FROM subagent_runs WHERE id = 'a1f3'").fetchone()[0]
        'done'
    """

    async def _hook(run: SubAgentRun) -> None:
        await asyncio.to_thread(persist_subagent_run, conn, run)

    return _hook


def sweep_orphaned_subagent_runs(conn: sqlite3.Connection, *, now_ns: int | None = None) -> int:
    """Mark previous-process ``pending``/``running`` rows ``orphaned`` (D3 boot sweep).

    A row surviving in ``pending``/``running`` status across a process
    restart cannot have a live in-memory task backing it — this reconciles
    storage with reality so Mission Control / ``sevn subagents list`` never
    shows a phantom "running" sub-agent (D10).

    Args:
        conn (sqlite3.Connection): Open, migrated ``sevn.db`` connection.
        now_ns (int | None): Clock override for ``finished_at_ns``; defaults
            to :func:`time.time_ns`.

    Returns:
        int: Number of rows transitioned.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> persist_subagent_run(conn, SubAgentRun(
        ...     id="a1f3", level=1, role="tier_b", specialist=None, parent_id=None,
        ...     session_id="s1", channel="telegram", task_summary="hi",
        ...     status=SubAgentStatus.RUNNING, started_at=1, finished_at=None,
        ...     trace_id=None,
        ... ))
        >>> sweep_orphaned_subagent_runs(conn, now_ns=99)
        1
        >>> conn.execute("SELECT status FROM subagent_runs WHERE id = 'a1f3'").fetchone()[0]
        'orphaned'
    """
    clock = time.time_ns() if now_ns is None else int(now_ns)
    before = conn.total_changes
    sql = f"""
        UPDATE subagent_runs
        SET status = 'orphaned', finished_at_ns = ?
        WHERE status IN ({",".join("?" * len(_STALE_STATUSES))})
    """  # nosec B608 — placeholders are bound status literals only
    conn.execute(sql, (clock, *_STALE_STATUSES))
    _commit_if_in_transaction(conn)
    return conn.total_changes - before


def prune_subagent_runs(
    conn: sqlite3.Connection, *, max_age_ns: int, now_ns: int | None = None
) -> int:
    """Delete terminal ``subagent_runs`` rows older than ``max_age_ns`` (D10 retention).

    Args:
        conn (sqlite3.Connection): Open, migrated ``sevn.db`` connection.
        max_age_ns (int): Retention window in nanoseconds.
        now_ns (int | None): Clock override; defaults to :func:`time.time_ns`.

    Returns:
        int: Number of rows deleted.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> persist_subagent_run(conn, SubAgentRun(
        ...     id="a1f3", level=1, role="tier_b", specialist=None, parent_id=None,
        ...     session_id="s1", channel="telegram", task_summary="hi",
        ...     status=SubAgentStatus.DONE, started_at=1, finished_at=10,
        ...     trace_id=None,
        ... ))
        >>> prune_subagent_runs(conn, max_age_ns=5, now_ns=100)
        1
    """
    clock = time.time_ns() if now_ns is None else int(now_ns)
    cutoff = clock - int(max_age_ns)
    before = conn.total_changes
    sql = f"""
        DELETE FROM subagent_runs
        WHERE status IN ({",".join("?" * len(_TERMINAL_STATUSES))})
        AND finished_at_ns IS NOT NULL AND finished_at_ns < ?
    """  # nosec B608 — placeholders are bound status literals only
    conn.execute(sql, (*_TERMINAL_STATUSES, cutoff))
    _commit_if_in_transaction(conn)
    return conn.total_changes - before


def load_subagent_result_body(conn: sqlite3.Connection, run_id: str) -> str | None:
    """Return persisted completion text for one sub-agent run, if any (#76).

    Args:
        conn (sqlite3.Connection): Open, migrated ``sevn.db`` connection.
        run_id (str): Target run id.

    Returns:
        str | None: Stored ``result_body`` or ``None`` when absent.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
        >>> from sevn.agent.subagents.storage import load_subagent_result_body, persist_subagent_run
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> run = SubAgentRun(
        ...     id="a1f3", level=2, role="tier_b", specialist=None, parent_id="p1",
        ...     session_id="s1", channel="telegram", task_summary="t",
        ...     status=SubAgentStatus.DONE, started_at=1, finished_at=2, trace_id=None,
        ... )
        >>> persist_subagent_run(conn, run, result_body="hello")
        >>> load_subagent_result_body(conn, "a1f3")
        'hello'
    """
    row = conn.execute(
        "SELECT result_body FROM subagent_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def mark_subagent_result_delivered(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    now_ns: int | None = None,
) -> None:
    """Record that a persisted sub-agent result reached the channel (#76).

    Args:
        conn (sqlite3.Connection): Open, migrated ``sevn.db`` connection.
        run_id (str): Target run id.
        now_ns (int | None): Clock override; defaults to :func:`time.time_ns`.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
        >>> from sevn.agent.subagents.storage import mark_subagent_result_delivered, persist_subagent_run
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> run = SubAgentRun(
        ...     id="a1f3", level=2, role="tier_b", specialist=None, parent_id="p1",
        ...     session_id="s1", channel="telegram", task_summary="t",
        ...     status=SubAgentStatus.DONE, started_at=1, finished_at=2, trace_id=None,
        ... )
        >>> persist_subagent_run(conn, run, result_body="hello")
        >>> mark_subagent_result_delivered(conn, "a1f3", now_ns=99)
        >>> conn.execute(
        ...     "SELECT result_delivered_at_ns FROM subagent_runs WHERE id = 'a1f3'",
        ... ).fetchone()[0]
        99
    """
    clock = time.time_ns() if now_ns is None else int(now_ns)
    conn.execute(
        "UPDATE subagent_runs SET result_delivered_at_ns = ? WHERE id = ?",
        (clock, run_id),
    )
    _commit_if_in_transaction(conn)


def _row_to_subagent_run(row: tuple[object, ...]) -> SubAgentRun:
    """Deserialize one ``subagent_runs`` SELECT row into a :class:`SubAgentRun`.

    Args:
        row (tuple[object, ...]): Twelve-column ``subagent_runs`` row.

    Returns:
        SubAgentRun: Parsed run record.

    Examples:
        >>> from sevn.agent.subagents.models import SubAgentStatus
        >>> run = _row_to_subagent_run(
        ...     ("a1f3", 2, "tier_b", None, "p1", "s1", "telegram", "t", "done", 1, 2, None)
        ... )
        >>> run.status == SubAgentStatus.DONE
        True
    """
    return SubAgentRun(
        id=str(row[0]),
        level=int(cast("int", row[1])),  # type: ignore[arg-type]
        role=str(row[2]),  # type: ignore[arg-type]
        specialist=str(row[3]) if row[3] is not None else None,
        parent_id=str(row[4]) if row[4] is not None else None,
        session_id=str(row[5]),
        channel=str(row[6]),
        task_summary=str(row[7]),
        status=SubAgentStatus(str(row[8])),
        started_at=int(cast("int", row[9])),
        finished_at=int(cast("int", row[10])) if row[10] is not None else None,
        trace_id=str(row[11]) if row[11] is not None else None,
    )


def _list_pending_subagent_deliveries(conn: sqlite3.Connection) -> list[SubAgentRun]:
    """Return done level-2 runs with persisted bodies not yet delivered.

    Args:
        conn (sqlite3.Connection): Open, migrated ``sevn.db`` connection.

    Returns:
        list[SubAgentRun]: Runs awaiting boot or live announce-back delivery.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
        >>> from sevn.agent.subagents.storage import persist_subagent_run
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> run = SubAgentRun(
        ...     id="a1f3", level=2, role="tier_b", specialist=None, parent_id="p1",
        ...     session_id="s1", channel="telegram", task_summary="t",
        ...     status=SubAgentStatus.DONE, started_at=1, finished_at=2, trace_id=None,
        ... )
        >>> persist_subagent_run(conn, run, result_body="hello")
        >>> pending = _list_pending_subagent_deliveries(conn)
        >>> pending[0].id
        'a1f3'
    """
    cursor = conn.execute(
        """
        SELECT
            id, level, role, specialist, parent_id, session_id, channel,
            task_summary, status, started_at_ns, finished_at_ns, trace_id
        FROM subagent_runs
        WHERE level = 2
          AND status = ?
          AND result_body IS NOT NULL
          AND result_delivered_at_ns IS NULL
        ORDER BY COALESCE(finished_at_ns, started_at_ns)
        """,
        (SubAgentStatus.DONE.value,),
    )
    return [_row_to_subagent_run(row) for row in cursor.fetchall()]


async def restore_pending_subagent_deliveries(
    *,
    conn: sqlite3.Connection,
    router: ChannelRouter,
) -> int:
    """Deliver persisted level-2 results that completed before the last crash (#76).

    Runs are delivered through :meth:`ChannelRouter.route_outgoing` (W18 ledger).
    Session ownership is enforced via :func:`sevn.gateway.session_manager.load_session_row`
    — a run whose ``session_id`` has no matching gateway session is skipped.

    Args:
        conn (sqlite3.Connection): Open, migrated ``sevn.db`` connection.
        router (ChannelRouter): Gateway router for outbound delivery.

    Returns:
        int: Number of runs successfully handed to ``route_outgoing``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(restore_pending_subagent_deliveries)
        True
    """
    from sevn.gateway.session_manager import load_session_row
    from sevn.gateway.subagents.subagents_announce import (
        deliver_subagent_result_through_ledger,
    )

    delivered = 0
    for run in _list_pending_subagent_deliveries(conn):
        sess = load_session_row(conn, run.session_id)
        if sess is None:
            logger.warning(
                "subagent_restore_session_missing run_id={} session_id={}",
                run.id,
                run.session_id,
            )
            continue
        if sess.session_id != run.session_id:
            continue
        body = load_subagent_result_body(conn, run.id)
        if body is None:
            continue
        try:
            if await deliver_subagent_result_through_ledger(
                router=router,
                conn=conn,
                run=run,
                session=sess,
                result_body=body,
            ):
                delivered += 1
        except Exception:
            logger.bind(subagent_id=run.id, session_id=run.session_id).exception(
                "subagent_restore_delivery_failed"
            )
            continue
    return delivered
