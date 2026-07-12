"""Tests for ``sevn.agent.subagents.storage`` (D10) — write-through, orphan sweep, prune."""

from __future__ import annotations

import sqlite3

from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
from sevn.agent.subagents.registry import SubAgentRegistry
from sevn.agent.subagents.storage import (
    persist_subagent_run,
    prune_subagent_runs,
    sqlite_persist_hook,
    sweep_orphaned_subagent_runs,
)
from sevn.storage.migrate import apply_migrations


def _migrated_conn() -> sqlite3.Connection:
    # check_same_thread=False mirrors sevn.storage.sqlite.connect: the persist
    # hook runs SQL via asyncio.to_thread, i.e. off the connection's home thread.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    apply_migrations(conn)
    return conn


def _sample_run(**overrides: object) -> SubAgentRun:
    base = {
        "id": "a1f3",
        "level": 1,
        "role": "tier_b",
        "specialist": None,
        "parent_id": None,
        "session_id": "s1",
        "channel": "telegram",
        "task_summary": "hi",
        "status": SubAgentStatus.PENDING,
        "started_at": 1,
        "finished_at": None,
        "trace_id": None,
    }
    base.update(overrides)
    return SubAgentRun(**base)  # type: ignore[arg-type]


def test_persist_subagent_run_inserts_row() -> None:
    conn = _migrated_conn()
    persist_subagent_run(conn, _sample_run())
    row = conn.execute(
        "SELECT id, level, role, status FROM subagent_runs WHERE id = 'a1f3'"
    ).fetchone()
    assert row == ("a1f3", 1, "tier_b", "pending")


def test_persist_subagent_run_upserts_on_transition() -> None:
    conn = _migrated_conn()
    persist_subagent_run(conn, _sample_run())
    persist_subagent_run(conn, _sample_run(status=SubAgentStatus.DONE, finished_at=42))
    row = conn.execute(
        "SELECT status, finished_at_ns FROM subagent_runs WHERE id = 'a1f3'",
    ).fetchone()
    assert row == ("done", 42)
    count = conn.execute("SELECT COUNT(*) FROM subagent_runs").fetchone()[0]
    assert count == 1


async def test_sqlite_persist_hook_round_trips_through_registry() -> None:
    conn = _migrated_conn()
    registry = SubAgentRegistry(persist=sqlite_persist_hook(conn))
    run = await registry.register(
        level=1,
        role="tier_b",
        session_id="s1",
        channel="telegram",
        task_summary="hi",
    )
    await registry.mark_running(run.id)
    await registry.mark_done(run.id, now_ns=99)

    row = conn.execute(
        "SELECT status, finished_at_ns FROM subagent_runs WHERE id = ?",
        (run.id,),
    ).fetchone()
    assert row == ("done", 99)


def test_sweep_orphaned_marks_stale_running_and_pending_only() -> None:
    conn = _migrated_conn()
    persist_subagent_run(conn, _sample_run(id="running1", status=SubAgentStatus.RUNNING))
    persist_subagent_run(conn, _sample_run(id="pending1", status=SubAgentStatus.PENDING))
    persist_subagent_run(conn, _sample_run(id="done1", status=SubAgentStatus.DONE, finished_at=5))

    changed = sweep_orphaned_subagent_runs(conn, now_ns=100)
    assert changed == 2

    statuses = dict(conn.execute("SELECT id, status FROM subagent_runs").fetchall())
    assert statuses["running1"] == "orphaned"
    assert statuses["pending1"] == "orphaned"
    assert statuses["done1"] == "done"


def test_prune_deletes_old_terminal_rows_only() -> None:
    conn = _migrated_conn()
    persist_subagent_run(
        conn, _sample_run(id="old_done", status=SubAgentStatus.DONE, finished_at=1)
    )
    persist_subagent_run(
        conn, _sample_run(id="recent_done", status=SubAgentStatus.DONE, finished_at=95)
    )
    persist_subagent_run(conn, _sample_run(id="still_running", status=SubAgentStatus.RUNNING))

    deleted = prune_subagent_runs(conn, max_age_ns=10, now_ns=100)
    assert deleted == 1

    remaining_ids = {r[0] for r in conn.execute("SELECT id FROM subagent_runs").fetchall()}
    assert remaining_ids == {"recent_done", "still_running"}
