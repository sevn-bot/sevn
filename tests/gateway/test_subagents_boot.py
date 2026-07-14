"""Tests for the sub-agents boot-construction hook (`sevn.gateway.subagents.subagents_boot`)."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from sevn.agent.subagents import SubAgentRegistry, SubAgentSupervisor
from sevn.gateway.subagents.subagents_boot import _construct_subagent_supervisor
from sevn.storage.migrate import apply_migrations


async def test_construct_subagent_supervisor_populates_app_state() -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    app = SimpleNamespace(state=SimpleNamespace())
    ctx = SimpleNamespace(
        conn=conn,
        workspace=SimpleNamespace(subagents=None),
        app=app,
        gateway_router=SimpleNamespace(),
    )

    await _construct_subagent_supervisor(ctx)  # type: ignore[arg-type]

    assert isinstance(app.state.subagent_registry, SubAgentRegistry)
    assert isinstance(app.state.subagent_supervisor, SubAgentSupervisor)


async def test_construct_subagent_supervisor_marks_stale_rows_orphaned() -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    conn.execute(
        """
        INSERT INTO subagent_runs (
            id, level, role, session_id, channel, status, started_at_ns
        ) VALUES ('stale1', 1, 'tier_b', 's', 'c', 'running', 1)
        """,
    )
    conn.commit()
    app = SimpleNamespace(state=SimpleNamespace())
    ctx = SimpleNamespace(
        conn=conn,
        workspace=SimpleNamespace(subagents=None),
        app=app,
        gateway_router=SimpleNamespace(),
    )

    await _construct_subagent_supervisor(ctx)  # type: ignore[arg-type]

    status = conn.execute("SELECT status FROM subagent_runs WHERE id = 'stale1'").fetchone()[0]
    assert status == "orphaned"
