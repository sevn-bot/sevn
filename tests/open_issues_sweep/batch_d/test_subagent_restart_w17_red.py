"""W17.4 — durable background subagent results (#76 → W19)."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
from sevn.agent.subagents.storage import persist_subagent_run
from sevn.gateway.subagents.subagents_boot import _construct_subagent_supervisor
from sevn.storage.migrate import apply_migrations
from tests.open_issues_sweep.batch_d.conftest import seed_gateway_session, table_columns


def _done_run(*, run_id: str = "sub1", session_id: str = "sess-a") -> SubAgentRun:
    return SubAgentRun(
        id=run_id,
        level=2,
        role="tier_b",
        specialist=None,
        parent_id="parent-1",
        session_id=session_id,
        channel="telegram",
        task_summary="research task",
        status=SubAgentStatus.DONE,
        started_at=1,
        finished_at=2,
        trace_id="trace-sub1",
    )


@pytest.mark.xfail(reason="green after W19: subagent result_body persisted", strict=False)
def test_persist_subagent_run_stores_result_body() -> None:
    """Completed runs must persist result text, not metadata only."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    run = _done_run()
    persist_subagent_run(conn, run, result_body="Final research summary.")
    cols = table_columns(conn, "subagent_runs")
    assert "result_body" in cols
    row = conn.execute(
        "SELECT result_body FROM subagent_runs WHERE id = 'sub1'",
    ).fetchone()
    assert row is not None
    assert str(row[0]) == "Final research summary."


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="green after W19: completed subagent delivered after restart", strict=False
)
async def test_boot_restores_and_delivers_completed_subagent_result() -> None:
    """A run that finished before crash must be delivered on boot, not orphaned."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    seed_gateway_session(conn, session_id="sess-a")
    run = _done_run()
    persist_subagent_run(conn, run, result_body="Done before crash.")

    router = MagicMock()
    router.route_outgoing = AsyncMock()
    router._sessions = MagicMock()
    router._sessions.dispatch_queue_snapshot.return_value = (0, False)
    router._steer_store = None

    app = SimpleNamespace(state=SimpleNamespace())
    ctx = SimpleNamespace(
        conn=conn,
        workspace=SimpleNamespace(subagents=None),
        app=app,
        gateway_router=router,
    )
    await _construct_subagent_supervisor(ctx)  # type: ignore[arg-type]

    router.route_outgoing.assert_awaited()
    sent = router.route_outgoing.await_args.args[0]
    assert "Done before crash" in sent.text


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W19: cross-session ownership enforced", strict=False)
async def test_restored_subagent_result_cannot_leak_to_other_session() -> None:
    """Ownership checks block delivery when session row does not match run.session_id."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    seed_gateway_session(conn, session_id="sess-owner")
    seed_gateway_session(conn, session_id="sess-other", user_id="99")
    run = _done_run(session_id="sess-owner")
    persist_subagent_run(conn, run, result_body="secret for owner")

    from sevn.agent.subagents.storage import restore_pending_subagent_deliveries

    router = MagicMock()
    router.route_outgoing = AsyncMock()
    leaks: list[Any] = []

    async def _capture(msg: Any) -> None:
        if msg.session_id != "sess-owner":
            leaks.append(msg.session_id)

    router.route_outgoing.side_effect = _capture

    await restore_pending_subagent_deliveries(conn=conn, router=router)
    assert leaks == []


@pytest.mark.xfail(reason="green after W19: announce-back reads persisted result", strict=False)
def test_subagent_announce_reads_result_from_storage_not_registry() -> None:
    """``build_announce_back_hook`` must load result body from SQLite after restart."""
    from sevn.gateway.subagents.subagents_announce import load_subagent_result_for_announce

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    run = _done_run()
    persist_subagent_run(conn, run, result_body="stored-only result")
    loaded = load_subagent_result_for_announce(conn, run.id)
    assert loaded == "stored-only result"
