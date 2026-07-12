"""SQLite helpers for C/D PlanGate persistence.

Module: sevn.agent.executors.plan_gate_store
Depends: sqlite3, time, uuid, sevn.agent.executors.cd_types, sevn.config.defaults

Exports:
    PendingPlanRecord — inserted ``pending_plans`` row identity.
    LoadedPendingPlan — row reloaded after daemon restart.
    store_pending_plan — persist one awaiting plan with JSON validation.
    load_awaiting_pending_plan — fetch awaiting row for resume.
    load_pending_plan_by_id — fetch one row by ``plan_id`` (any status).
    update_pending_plan_status — transition an awaiting row to a terminal status.
    expire_pending_plans — mark expired awaiting rows during gateway sweeps.
    supersede_pending_plan — mark one awaiting row superseded.
    supersede_awaiting_for_session — supersede all awaiting rows for a session.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from sevn.agent.executors.cd_types import CdBackendLiteral, Plan
from sevn.config.defaults import DEFAULT_PLAN_APPROVAL_TTL_SECONDS

if TYPE_CHECKING:
    import sqlite3


@dataclass(frozen=True)
class PendingPlanRecord:
    """Identity and expiry for one persisted C/D plan."""

    plan_id: str
    expires_at_ns: int


@dataclass(frozen=True)
class LoadedPendingPlan:
    """One ``pending_plans`` row loaded after daemon restart."""

    plan_id: str
    session_id: str
    turn_id: str
    c_d_backend: CdBackendLiteral
    plan: Plan
    status: str
    expires_at_ns: int


def store_pending_plan(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    turn_id: str,
    plan: Plan,
    c_d_backend: CdBackendLiteral,
    now_ns: int | None = None,
    ttl_seconds: int = DEFAULT_PLAN_APPROVAL_TTL_SECONDS,
) -> PendingPlanRecord:
    """Persist one awaiting plan row.

    Args:
        conn (sqlite3.Connection): Migrated ``sevn.db`` connection.
        session_id (str): Gateway session id.
        turn_id (str): User turn id.
        plan (Plan): JSON-serialisable C/D plan.
        c_d_backend (CdBackendLiteral): Backend used by the turn.
        now_ns (int | None, optional): Clock override. Defaults to ``time.time_ns()``.
        ttl_seconds (int, optional): Approval TTL in seconds. Defaults to 15 minutes.

    Returns:
        PendingPlanRecord: Persisted plan id and expiration time.

    Raises:
        sqlite3.IntegrityError: If an awaiting row already exists for ``(session_id, turn_id)``.

    Examples:
        >>> import sqlite3
        >>> from sevn.agent.executors.cd_types import Plan, PlanStep
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> plan = Plan(
        ...     steps=[PlanStep(id="1", title="review")],
        ...     summary="s",
        ...     meta=Plan.Meta(complexity="C", registry_version=1),
        ... )
        >>> rec = store_pending_plan(
        ...     conn, session_id="s", turn_id="t", plan=plan, c_d_backend="dspy", now_ns=1
        ... )
        >>> bool(rec.plan_id)
        True
    """

    clock = time.time_ns() if now_ns is None else int(now_ns)
    expires_at_ns = clock + int(ttl_seconds) * 1_000_000_000
    plan_json = plan.model_dump_json()
    plan_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO pending_plans (
            plan_id, session_id, turn_id, c_d_backend, plan_json,
            status, created_at_ns, expires_at_ns, updated_at_ns
        ) VALUES (?, ?, ?, ?, ?, 'awaiting', ?, ?, ?)
        """,
        (plan_id, session_id, turn_id, c_d_backend, plan_json, clock, expires_at_ns, clock),
    )
    return PendingPlanRecord(plan_id=plan_id, expires_at_ns=expires_at_ns)


def expire_pending_plans(conn: sqlite3.Connection, *, now_ns: int | None = None) -> int:
    """Expire awaiting PlanGate rows whose TTL elapsed.

    Args:
        conn (sqlite3.Connection): Migrated ``sevn.db`` connection.
        now_ns (int | None, optional): Clock override. Defaults to ``time.time_ns()``.

    Returns:
        int: Number of rows updated.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> expire_pending_plans(conn, now_ns=1)
        0
    """

    clock = time.time_ns() if now_ns is None else int(now_ns)
    before = conn.total_changes
    conn.execute(
        """
        UPDATE pending_plans
        SET status = 'expired', updated_at_ns = ?
        WHERE status = 'awaiting' AND expires_at_ns <= ?
        """,
        (clock, clock),
    )
    return int(conn.total_changes - before)


def load_awaiting_pending_plan(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    turn_id: str,
) -> LoadedPendingPlan | None:
    """Load the active awaiting plan for ``(session_id, turn_id)`` if present.

    Args:
        conn (sqlite3.Connection): Migrated ``sevn.db`` connection.
        session_id (str): Gateway session id.
        turn_id (str): User turn id.

    Returns:
        LoadedPendingPlan | None: Row when status is ``awaiting``; else ``None``.

    Examples:
        >>> import sqlite3
        >>> from sevn.agent.executors.cd_types import Plan, PlanStep
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> plan = Plan(
        ...     steps=[PlanStep(id="1", title="review")],
        ...     summary="s",
        ...     meta=Plan.Meta(complexity="C", registry_version=1),
        ... )
        >>> _ = store_pending_plan(
        ...     conn, session_id="s", turn_id="t", plan=plan, c_d_backend="dspy", now_ns=1
        ... )
        >>> loaded = load_awaiting_pending_plan(conn, session_id="s", turn_id="t")
        >>> loaded is not None and loaded.plan.summary == "s"
        True
    """

    row = conn.execute(
        """
        SELECT plan_id, session_id, turn_id, c_d_backend, plan_json, status, expires_at_ns
        FROM pending_plans
        WHERE session_id = ? AND turn_id = ? AND status = 'awaiting'
        """,
        (session_id, turn_id),
    ).fetchone()
    if row is None:
        return None
    plan_id, sid, tid, backend, plan_json, status, expires_at_ns = row
    return LoadedPendingPlan(
        plan_id=str(plan_id),
        session_id=str(sid),
        turn_id=str(tid),
        c_d_backend=cast("CdBackendLiteral", str(backend)),
        plan=Plan.model_validate_json(str(plan_json)),
        status=str(status),
        expires_at_ns=int(expires_at_ns),
    )


def load_pending_plan_by_id(
    conn: sqlite3.Connection,
    *,
    plan_id: str,
) -> LoadedPendingPlan | None:
    """Load one ``pending_plans`` row by primary key.

    Args:
        conn (sqlite3.Connection): Migrated ``sevn.db`` connection.
        plan_id (str): Plan row id.

    Returns:
        LoadedPendingPlan | None: Row when present; else ``None``.

    Examples:
        >>> import sqlite3
        >>> from sevn.agent.executors.cd_types import Plan, PlanStep
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> plan = Plan(
        ...     steps=[PlanStep(id="1", title="review")],
        ...     summary="s",
        ...     meta=Plan.Meta(complexity="C", registry_version=1),
        ... )
        >>> rec = store_pending_plan(
        ...     conn, session_id="s", turn_id="t", plan=plan, c_d_backend="dspy", now_ns=1
        ... )
        >>> loaded = load_pending_plan_by_id(conn, plan_id=rec.plan_id)
        >>> loaded is not None and loaded.status == "awaiting"
        True
    """

    row = conn.execute(
        """
        SELECT plan_id, session_id, turn_id, c_d_backend, plan_json, status, expires_at_ns
        FROM pending_plans
        WHERE plan_id = ?
        """,
        (plan_id,),
    ).fetchone()
    if row is None:
        return None
    pid, sid, tid, backend, plan_json, status, expires_at_ns = row
    return LoadedPendingPlan(
        plan_id=str(pid),
        session_id=str(sid),
        turn_id=str(tid),
        c_d_backend=cast("CdBackendLiteral", str(backend)),
        plan=Plan.model_validate_json(str(plan_json)),
        status=str(status),
        expires_at_ns=int(expires_at_ns),
    )


def update_pending_plan_status(
    conn: sqlite3.Connection,
    *,
    plan_id: str,
    status: str,
    now_ns: int | None = None,
) -> bool:
    """Update one awaiting plan row to a terminal status.

    Args:
        conn (sqlite3.Connection): Migrated ``sevn.db`` connection.
        plan_id (str): Plan row id.
        status (str): Target status (``approved``, ``rejected``, etc.).
        now_ns (int | None, optional): Clock override. Defaults to ``time.time_ns()``.

    Returns:
        bool: ``True`` when a row was updated.

    Examples:
        >>> import sqlite3
        >>> from sevn.agent.executors.cd_types import Plan, PlanStep
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> plan = Plan(
        ...     steps=[PlanStep(id="1", title="review")],
        ...     summary="s",
        ...     meta=Plan.Meta(complexity="C", registry_version=1),
        ... )
        >>> rec = store_pending_plan(
        ...     conn, session_id="s", turn_id="t", plan=plan, c_d_backend="dspy", now_ns=1
        ... )
        >>> update_pending_plan_status(conn, plan_id=rec.plan_id, status="approved", now_ns=2)
        True
    """

    clock = time.time_ns() if now_ns is None else int(now_ns)
    before = conn.total_changes
    conn.execute(
        """
        UPDATE pending_plans
        SET status = ?, updated_at_ns = ?
        WHERE plan_id = ? AND status = 'awaiting'
        """,
        (status, clock, plan_id),
    )
    return bool(conn.total_changes - before)


def supersede_awaiting_for_session(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    now_ns: int | None = None,
) -> list[str]:
    """Mark every awaiting plan for ``session_id`` superseded.

    Args:
        conn (sqlite3.Connection): Migrated ``sevn.db`` connection.
        session_id (str): Gateway session id.
        now_ns (int | None, optional): Clock override. Defaults to ``time.time_ns()``.

    Returns:
        list[str]: ``plan_id`` values that were superseded.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> supersede_awaiting_for_session(conn, session_id="s", now_ns=1)
        []
    """

    clock = time.time_ns() if now_ns is None else int(now_ns)
    rows = conn.execute(
        """
        SELECT plan_id FROM pending_plans
        WHERE session_id = ? AND status = 'awaiting'
        """,
        (session_id,),
    ).fetchall()
    plan_ids = [str(r[0]) for r in rows]
    if not plan_ids:
        return []
    conn.execute(
        """
        UPDATE pending_plans
        SET status = 'superseded', updated_at_ns = ?
        WHERE session_id = ? AND status = 'awaiting'
        """,
        (clock, session_id),
    )
    return plan_ids


def supersede_pending_plan(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    turn_id: str,
    now_ns: int | None = None,
) -> int:
    """Mark the awaiting row for ``(session_id, turn_id)`` superseded.

    Args:
        conn (sqlite3.Connection): Migrated ``sevn.db`` connection.
        session_id (str): Gateway session id.
        turn_id (str): User turn id.
        now_ns (int | None, optional): Clock override. Defaults to ``time.time_ns()``.

    Returns:
        int: Number of rows updated.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> supersede_pending_plan(conn, session_id="s", turn_id="t", now_ns=1)
        0
    """

    clock = time.time_ns() if now_ns is None else int(now_ns)
    before = conn.total_changes
    conn.execute(
        """
        UPDATE pending_plans
        SET status = 'superseded', updated_at_ns = ?
        WHERE session_id = ? AND turn_id = ? AND status = 'awaiting'
        """,
        (clock, session_id, turn_id),
    )
    return int(conn.total_changes - before)


__all__ = [
    "LoadedPendingPlan",
    "PendingPlanRecord",
    "expire_pending_plans",
    "load_awaiting_pending_plan",
    "load_pending_plan_by_id",
    "store_pending_plan",
    "supersede_awaiting_for_session",
    "supersede_pending_plan",
    "update_pending_plan_status",
]
