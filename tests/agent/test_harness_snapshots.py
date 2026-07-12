"""Tests for harness snapshot discipline (`specs/16-harness-discipline.md`)."""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any
from unittest.mock import patch

import pytest

from sevn.agent.harness.snapshots import (
    ActiveRunSnapshotWrite,
    HarnessSnapshotSanitisationError,
    delete_active_run_snapshot,
    format_upgrade_paused_notification,
    get_or_create_turn_replay_job_id,
    pending_resume_group_count,
    persist_run_snapshot,
    redacted_inspect_summary,
    sanitize_in_flight_tools,
    sanitize_plan_state,
    session_has_active_run_for_replay,
    sweep_active_run_snapshots,
)
from sevn.agent.harness.zombie import ZombieWatchQueue
from sevn.config.defaults import HARNESS_SNAPSHOT_GC_ORPHAN_MAX_AGE_NS
from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway.boot import run_harness_boot_sweep
from sevn.storage.migrate import apply_migrations


class _ListSink:
    """Minimal ``TraceSink`` for tests."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    return conn


def test_sanitize_plan_state_allowlist_roundtrip() -> None:
    raw = {
        "turn_id": "t1",
        "run_id": "r1",
        "persona": "standard",
        "subagent_depth": 0,
        "rounds_outer": 2,
        "rounds_inner_budget_key": "k",
        "plan_gate": "none",
        "registry_version": 3,
        "c_d_backend": "dspy",
    }
    assert sanitize_plan_state(raw) == raw


def test_sanitize_plan_state_rejects_forbidden_args_key() -> None:
    with pytest.raises(HarnessSnapshotSanitisationError):
        sanitize_plan_state({"turn_id": "t", "args": [1, 2]})


def test_sanitize_plan_state_rejects_unknown_key() -> None:
    with pytest.raises(HarnessSnapshotSanitisationError):
        sanitize_plan_state({"turn_id": "t", "extra_field": 1})


def test_sanitize_in_flight_tools_rejects_arguments() -> None:
    with pytest.raises(HarnessSnapshotSanitisationError):
        sanitize_in_flight_tools([{"name": "x", "arguments": {}}])


def test_sanitize_in_flight_tools_roundtrip() -> None:
    out = sanitize_in_flight_tools(
        [{"name": "n", "call_id": "c", "abortable": False, "phase": "executing"}],
    )
    assert out[0]["name"] == "n"


@pytest.mark.parametrize(
    ("status", "expect_block"),
    [
        ("active", True),
        ("pending_resume", True),
        ("sent", False),
        ("cancelled", False),
        ("failed", False),
        ("abandoned", False),
    ],
)
def test_session_replay_409_precondition_by_status(status: str, expect_block: bool) -> None:
    """``session_has_active_run_for_replay`` matches §2.3 (active / pending_resume only)."""
    conn = _memory_db()
    conn.execute(
        """INSERT INTO active_run_snapshots (
            run_id, session_id, tier, plan_state, in_flight_tools,
            excerpt, status, created_at_ns, updated_at_ns
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("r-status", "sess-x", "B", "{}", "[]", "e", status, 1, 2),
    )
    conn.commit()
    assert session_has_active_run_for_replay(conn, "sess-x") is expect_block


def test_turn_replay_job_id_idempotent() -> None:
    conn = _memory_db()
    a = get_or_create_turn_replay_job_id(conn, session_id="s", turn_id="t1", now_ns=100)
    b = get_or_create_turn_replay_job_id(conn, session_id="s", turn_id="t1", now_ns=200)
    assert a == b
    c = get_or_create_turn_replay_job_id(conn, session_id="s", turn_id="t2", now_ns=300)
    assert c != a


def test_upgrade_grouped_notification_single_line_for_n_snapshots() -> None:
    """§4.2: one operator string derived from aggregate ``N``, not N separate lines."""
    conn = _memory_db()
    for i in range(5):
        conn.execute(
            """INSERT INTO active_run_snapshots (
                run_id, session_id, tier, plan_state, in_flight_tools,
                excerpt, status, created_at_ns, updated_at_ns
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (f"run-{i}", f"sess-{i}", "B", "{}", "[]", "e", "pending_resume", 1, 2),
        )
    conn.commit()
    n = pending_resume_group_count(conn)
    assert n == 5
    msg = format_upgrade_paused_notification(n)
    assert msg == "5 runs paused for upgrade"
    assert msg.count("paused for upgrade") == 1


@pytest.mark.asyncio
async def test_persist_and_session_replay_guard() -> None:
    conn = _memory_db()
    sink = _ListSink()
    row = ActiveRunSnapshotWrite(
        run_id="run-1",
        session_id="sess-1",
        tier="B",
        plan_state={"turn_id": "ta", "run_id": "run-1"},
        in_flight_tools=[{"name": "noop", "abortable": True}],
        excerpt="hi",
        status="active",
        created_at_ns=100,
        updated_at_ns=100,
    )
    await persist_run_snapshot(conn=conn, row=row, trace=sink, boundary="llm")
    assert session_has_active_run_for_replay(conn, "sess-1") is True
    assert any(e.kind == "harness.snapshot.write" for e in sink.events)


@pytest.mark.asyncio
async def test_persist_sql_failure_swallows() -> None:
    conn = sqlite3.connect(":memory:")
    sink = _ListSink()
    row = ActiveRunSnapshotWrite(
        run_id="r",
        session_id="s",
        tier="A",
        plan_state={"turn_id": "t", "run_id": "r"},
        in_flight_tools=[],
        excerpt="x",
        status="active",
        created_at_ns=1,
        updated_at_ns=1,
    )
    await persist_run_snapshot(conn=conn, row=row, trace=sink)
    conn.close()


def test_gc_deletes_older_than_fourteen_days() -> None:
    now = 1_000_000_000_000_000
    cutoff = now - HARNESS_SNAPSHOT_GC_ORPHAN_MAX_AGE_NS
    conn = _memory_db()
    conn.execute(
        """INSERT INTO active_run_snapshots (
            run_id, session_id, tier, plan_state, in_flight_tools,
            excerpt, status, created_at_ns, updated_at_ns
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("old", "s", "B", "{}", "[]", "e", "active", 0, cutoff - 1),
    )
    conn.execute(
        """INSERT INTO active_run_snapshots (
            run_id, session_id, tier, plan_state, in_flight_tools,
            excerpt, status, created_at_ns, updated_at_ns
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("edge", "s", "B", "{}", "[]", "e", "pending_resume", 0, cutoff),
    )
    conn.commit()

    async def _run() -> tuple[_ListSink, object]:
        sink = _ListSink()
        res = await sweep_active_run_snapshots(conn=conn, trace=sink, now_ns=now)
        return sink, res

    sink, res = asyncio.run(_run())
    assert res.gc_deleted_count == 1
    left = conn.execute(
        "SELECT run_id FROM active_run_snapshots ORDER BY run_id",
    ).fetchall()
    assert [r[0] for r in left] == ["edge"]
    gc_events = [e for e in sink.events if e.kind == "harness.snapshot.gc_orphan"]
    assert len(gc_events) >= 1
    assert gc_events[0].attrs.get("deleted") == 1


@pytest.mark.asyncio
async def test_sweep_resume_prompt_vs_auto_resume_b() -> None:
    now = 500_000_000_000_000
    conn = _memory_db()
    conn.execute(
        """INSERT INTO active_run_snapshots (
            run_id, session_id, tier, plan_state, in_flight_tools,
            excerpt, status, created_at_ns, updated_at_ns
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("b1", "s1", "B", "{}", "[]", "e", "pending_resume", 0, now),
    )
    conn.execute(
        """INSERT INTO active_run_snapshots (
            run_id, session_id, tier, plan_state, in_flight_tools,
            excerpt, status, created_at_ns, updated_at_ns
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("c1", "s2", "C", "{}", "[]", "e", "active", 0, now),
    )
    conn.commit()

    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {
                "restart": {"auto_resume_b": True},
                "token": "${SECRET:keychain:sevn.gateway.token}",
            },
        },
    )
    sink = _ListSink()
    out = await sweep_active_run_snapshots(conn=conn, trace=sink, workspace=cfg, now_ns=now)
    assert len(out.auto_resumed_tier_b) == 1
    assert len(out.owner_prompt_runs) == 1
    kinds = [e.kind for e in sink.events]
    assert "harness.auto_resume_b" in kinds
    assert kinds.count("harness.boot.resume_prompt") == 1


@pytest.mark.asyncio
async def test_run_harness_boot_sweep_delegates() -> None:
    conn = _memory_db()
    sink = _ListSink()
    res = await run_harness_boot_sweep(conn=conn, trace=sink, now_ns=1)
    assert res.gc_deleted_count == 0


def test_pending_resume_group_count() -> None:
    conn = _memory_db()
    conn.execute(
        """INSERT INTO active_run_snapshots (
            run_id, session_id, tier, plan_state, in_flight_tools,
            excerpt, status, created_at_ns, updated_at_ns
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("a", "s", "B", "{}", "[]", "e", "pending_resume", 1, 2),
    )
    conn.execute(
        """INSERT INTO active_run_snapshots (
            run_id, session_id, tier, plan_state, in_flight_tools,
            excerpt, status, created_at_ns, updated_at_ns
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("b", "s", "B", "{}", "[]", "e", "pending_resume", 1, 2),
    )
    assert pending_resume_group_count(conn) == 2


def test_redacted_inspect_summary() -> None:
    s = redacted_inspect_summary(
        excerpt="path .llmignore/foo",
        tier="D",
        created_at_ns=0,
        updated_at_ns=0,
        now_ns=1_000_000_000,
    )
    assert s["excerpt"] == "[REDACTED_PATH]"
    s2 = redacted_inspect_summary(
        excerpt="/abs/path",
        tier="B",
        created_at_ns=0,
        updated_at_ns=0,
        now_ns=1_000_000_000,
    )
    assert s2["excerpt"] == "[REDACTED_TEXT]"


def test_delete_active_run_snapshot() -> None:
    conn = _memory_db()
    conn.execute(
        """INSERT INTO active_run_snapshots (
            run_id, session_id, tier, plan_state, in_flight_tools,
            excerpt, status, created_at_ns, updated_at_ns
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("x", "s", "B", "{}", "[]", "e", "active", 1, 2),
    )
    delete_active_run_snapshot(conn, "x")
    assert conn.execute("SELECT COUNT(*) FROM active_run_snapshots").fetchone()[0] == 0


def test_workspace_parse_harness_keys() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {
                "queue_mode": "steer",
                "restart": {"auto_resume_b": True},
                "token": "${SECRET:keychain:sevn.gateway.token}",
            },
            "replay": {"max_per_day": 10},
            "harness": {"snapshot": {"triager_tier_a": True}},
        },
    )
    assert cfg.gateway is not None
    assert cfg.gateway.queue_mode == "steer"
    assert cfg.gateway.restart is not None
    assert cfg.gateway.restart.auto_resume_b is True
    assert cfg.replay is not None
    assert cfg.replay.max_per_day == 10
    assert cfg.harness is not None
    assert cfg.harness.snapshot is not None
    assert cfg.harness.snapshot.triager_tier_a is True


@pytest.mark.asyncio
async def test_zombie_queue_rejects_when_at_capacity() -> None:
    small = 2
    with patch("sevn.agent.harness.zombie.HARNESS_ZOMBIE_MAX_PENDING", small):
        sink = _ListSink()
        q = ZombieWatchQueue(sink)
        assert await q.try_enqueue(session_id="s", turn_id="t", tool_name="a", call_id="1")
        assert await q.try_enqueue(session_id="s", turn_id="t", tool_name="b", call_id="2")
        assert not await q.try_enqueue(session_id="s", turn_id="t", tool_name="c", call_id="3")
    rejected = [e for e in sink.events if e.kind == "harness.zombie.rejected"]
    assert len(rejected) == 1


@pytest.mark.asyncio
async def test_zombie_drain_emits_complete() -> None:
    sink = _ListSink()
    q = ZombieWatchQueue(sink)
    await q.try_enqueue(session_id="s", turn_id="t", tool_name="z", call_id=None)
    await q.drain_step()
    kinds = [e.kind for e in sink.events]
    assert "zombie.enqueue" in kinds
    assert "zombie.drain" in kinds
    assert "zombie.complete" in kinds
