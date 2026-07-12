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
import time
from typing import TYPE_CHECKING

from loguru import logger

from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus

if TYPE_CHECKING:
    import sqlite3

    from sevn.agent.subagents.registry import PersistHook


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
    "persist_subagent_run",
    "prune_subagent_runs",
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


def persist_subagent_run(conn: sqlite3.Connection, run: SubAgentRun) -> None:
    """Upsert one ``subagent_runs`` row from a registry transition (D10 write-through).

    Args:
        conn (sqlite3.Connection): Open, migrated ``sevn.db`` connection.
        run (SubAgentRun): Current row state.

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
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO subagent_runs (
                id, level, role, specialist, parent_id, session_id, channel,
                task_summary, status, started_at_ns, finished_at_ns, trace_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        conn.commit()
    except Exception:
        logger.bind(subagent_id=run.id).exception("persist_subagent_run SQL failed")


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
    conn.commit()
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
    conn.commit()
    return conn.total_changes - before
