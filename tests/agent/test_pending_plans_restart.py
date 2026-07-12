"""``pending_plans`` survives closing and reopening ``sevn.db`` (Wave 8 resume gate)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sevn.agent.executors.cd_types import Plan, PlanStep
from sevn.agent.executors.plan_gate_store import (
    load_awaiting_pending_plan,
    store_pending_plan,
)
from sevn.storage.migrate import apply_migrations


def _open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    apply_migrations(conn)
    return conn


def _plan() -> Plan:
    return Plan(
        steps=[PlanStep(id="1", title="resume step")],
        summary="awaiting owner approval",
        meta=Plan.Meta(complexity="C", registry_version=1),
    )


def test_pending_plans_survives_daemon_restart(tmp_path: Path) -> None:
    """Persist awaiting plan, close DB, reopen — row reloads via ``load_awaiting_pending_plan``."""
    db_path = tmp_path / "sevn.db"
    conn = _open_db(db_path)
    stored = store_pending_plan(
        conn,
        session_id="sess-restart",
        turn_id="turn-restart",
        plan=_plan(),
        c_d_backend="dspy",
        now_ns=100,
    )
    conn.commit()
    conn.close()

    conn2 = _open_db(db_path)
    loaded = load_awaiting_pending_plan(
        conn2,
        session_id="sess-restart",
        turn_id="turn-restart",
    )
    conn2.close()

    assert loaded is not None
    assert loaded.plan_id == stored.plan_id
    assert loaded.status == "awaiting"
    assert loaded.c_d_backend == "dspy"
    assert loaded.plan.summary == "awaiting owner approval"
    assert loaded.expires_at_ns == stored.expires_at_ns
