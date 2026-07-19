"""Tests for ``sevn.agent.subagents.storage`` (D10) — write-through, orphan sweep, prune."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
from sevn.agent.subagents.registry import SubAgentRegistry
from sevn.agent.subagents.storage import (
    persist_subagent_run,
    prune_subagent_runs,
    sqlite_persist_hook,
    sweep_orphaned_subagent_runs,
)
from sevn.storage.migrate import apply_migrations

if TYPE_CHECKING:
    import pytest
    from loguru import Message


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


def _capture_loguru(*, level: str = "ERROR") -> tuple[list[str], int]:
    from loguru import logger as loguru_logger

    captured: list[str] = []

    def _sink(message: Message) -> None:
        captured.append(str(message))

    sink_id = loguru_logger.add(_sink, level=level)
    return captured, sink_id


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


def test_persist_subagent_run_skips_commit_outside_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D1: do not call ``conn.commit()`` when ``conn.in_transaction`` is false."""
    conn = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    apply_migrations(conn)
    commits: list[bool] = []

    def _tracked_commit(connection: sqlite3.Connection) -> None:
        if connection.in_transaction:
            commits.append(True)
            connection.commit()

    monkeypatch.setattr(
        "sevn.agent.subagents.storage._commit_if_in_transaction",
        _tracked_commit,
    )
    persist_subagent_run(conn, _sample_run())
    assert commits == []


def test_persist_subagent_run_success_emits_no_error_log() -> None:
    """D1: a normal write persists quietly — no ERROR/traceback."""
    from loguru import logger as loguru_logger

    conn = _migrated_conn()
    captured, sink_id = _capture_loguru(level="ERROR")
    try:
        persist_subagent_run(conn, _sample_run())
    finally:
        loguru_logger.remove(sink_id)
    assert captured == []


def test_persist_subagent_run_sqlite_error_logged_once() -> None:
    """D1: real SQL failures log once via ``sqlite3.Error`` — not bare ``Exception`` spam."""
    from loguru import logger as loguru_logger

    conn = _migrated_conn()
    run = _sample_run()
    captured, sink_id = _capture_loguru(level="ERROR")
    conn.close()
    try:
        persist_subagent_run(conn, run)
    finally:
        loguru_logger.remove(sink_id)
    assert len(captured) == 1
    assert "persist_subagent_run SQL failed" in captured[0]
    assert run.id in captured[0]
    assert run.session_id in captured[0]


def test_sweep_orphaned_skips_commit_outside_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D1: ``sweep_orphaned_subagent_runs`` (:248) must not spuriously commit."""
    conn = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    apply_migrations(conn)
    persist_subagent_run(conn, _sample_run(id="run1", status=SubAgentStatus.RUNNING))
    commits: list[bool] = []

    def _tracked_commit(connection: sqlite3.Connection) -> None:
        if connection.in_transaction:
            commits.append(True)
            connection.commit()

    monkeypatch.setattr(
        "sevn.agent.subagents.storage._commit_if_in_transaction",
        _tracked_commit,
    )
    sweep_orphaned_subagent_runs(conn, now_ns=100)
    assert commits == []


def test_prune_subagent_runs_skips_commit_outside_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D1: ``prune_subagent_runs`` (:289) must not spuriously commit."""
    conn = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    apply_migrations(conn)
    persist_subagent_run(
        conn, _sample_run(id="old_done", status=SubAgentStatus.DONE, finished_at=1)
    )
    commits: list[bool] = []

    def _tracked_commit(connection: sqlite3.Connection) -> None:
        if connection.in_transaction:
            commits.append(True)
            connection.commit()

    monkeypatch.setattr(
        "sevn.agent.subagents.storage._commit_if_in_transaction",
        _tracked_commit,
    )
    prune_subagent_runs(conn, max_age_ns=10, now_ns=100)
    assert commits == []
