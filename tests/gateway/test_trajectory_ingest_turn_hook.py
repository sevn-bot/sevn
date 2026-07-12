"""Post-turn trajectory ingest hook tests (Batch C lane #3)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sevn.agent.tracing.traces_migrate import apply_traces_migrations
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.post_turn_hooks import (
    PostTurnContext,
    clear_post_turn_hooks,
    register_post_turn_hook,
    run_post_turn_hooks,
)
from sevn.gateway.trajectory_ingest_hooks import _post_turn_trajectory_ingest
from sevn.storage.migrate import apply_migrations
from sevn.storage.paths import traces_sqlite_path
from sevn.workspace.layout import WorkspaceLayout


@pytest.fixture(autouse=True)
def _hooks() -> None:
    clear_post_turn_hooks()
    register_post_turn_hook("trajectory_ingest", _post_turn_trajectory_ingest, priority=30)
    yield
    clear_post_turn_hooks()


def _seed_trace(layout: WorkspaceLayout, *, turn_id: str) -> None:
    layout.dot_sevn.mkdir(parents=True, exist_ok=True)
    traces_path = traces_sqlite_path(layout.dot_sevn)
    conn = sqlite3.connect(traces_path)
    apply_traces_migrations(conn)
    conn.execute(
        """INSERT INTO trace_events (
            span_id, parent_span_id, session_id, turn_id, tier, kind,
            ts_start_ns, ts_end_ns, status, attrs_json
        ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 'ok', ?)""",
        (
            "span-1",
            "sess-1",
            turn_id,
            "C",
            "triage.complete",
            100,
            101,
            json.dumps(
                {
                    "intent": "chat",
                    "complexity": "C",
                    "channel": "telegram",
                    "budget_regime": "normal",
                    "model_id": "minimax/MiniMax-M2.7",
                },
            ),
        ),
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_post_turn_hook_ingests_trajectory_fact(tmp_path: Path) -> None:
    """Simulated turn end produces ``trajectory_fact`` without manual INSERT."""
    layout = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    _seed_trace(layout, turn_id="turn-hook-1")
    sevn_conn = sqlite3.connect(":memory:", check_same_thread=False)
    apply_migrations(sevn_conn)

    router = MagicMock()
    router._content_root = layout.content_root
    router._workspace = WorkspaceConfig.minimal()

    ctx = PostTurnContext(
        router=router,
        conn=sevn_conn,
        trace=MagicMock(),
        session_id="sess-1",
        correlation_id="turn-hook-1",
        terminal_status="ok",
        turn_wall_ns=1_000_000_000,
    )
    with (
        patch("sevn.gateway.agent_turn._emit_gateway_span", new_callable=AsyncMock),
        patch("sevn.gateway.post_turn_hooks.record_turn_finished"),
    ):
        await run_post_turn_hooks(ctx)
        await asyncio.sleep(0.6)

    row = sevn_conn.execute(
        "SELECT turn_id, tier, channel FROM trajectory_fact WHERE turn_id = ?",
        ("turn-hook-1",),
    ).fetchone()
    assert row is not None
    assert row[0] == "turn-hook-1"
    assert row[1] == "C"
    assert row[2] == "telegram"
    sevn_conn.close()
