"""Boot-resume gate: snapshots survive process restart (`plan/v1-tasks-ordered.md` Wave 5).

Covers tier **B** (``pending_resume``) and stub tier **C** (``active``) rows through
``run_harness_boot_sweep`` after closing and reopening ``sevn.db``.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from sevn.agent.harness.snapshots import (
    ActiveRunSnapshotWrite,
    persist_run_snapshot,
    sweep_active_run_snapshots,
)
from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway.boot import run_harness_boot_sweep
from sevn.storage.migrate import apply_migrations


class _ListSink:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def emit(self, event: object) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    apply_migrations(conn)
    return conn


@pytest.mark.asyncio
async def test_active_run_snapshot_survives_restart_and_boot_sweep(tmp_path: Path) -> None:
    """Persist mid-flight rows, reopen DB, classify resume offers (tier B + C)."""
    db_path = tmp_path / "sevn.db"
    now = time.time_ns()
    sink = _ListSink()

    conn = _open_db(db_path)
    await persist_run_snapshot(
        conn=conn,
        row=ActiveRunSnapshotWrite(
            run_id="run-b-resume",
            session_id="sess-b",
            tier="B",
            plan_state={"turn_id": "turn-b", "run_id": "run-b-resume"},
            in_flight_tools=[{"name": "tick", "abortable": True, "phase": "executing"}],
            excerpt="tier-B mid-turn",
            status="pending_resume",
            created_at_ns=now,
            updated_at_ns=now,
        ),
        trace=sink,
        boundary="tool",
    )
    await persist_run_snapshot(
        conn=conn,
        row=ActiveRunSnapshotWrite(
            run_id="run-c-resume",
            session_id="sess-c",
            tier="C",
            plan_state={"turn_id": "turn-c", "run_id": "run-c-resume", "c_d_backend": "dspy"},
            in_flight_tools=[],
            excerpt="tier-C stub harness",
            status="active",
            created_at_ns=now,
            updated_at_ns=now,
        ),
        trace=sink,
        boundary="llm",
    )
    conn.commit()
    conn.close()

    conn2 = _open_db(db_path)
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {
                "restart": {"auto_resume_b": False},
                "token": "${SECRET:keychain:sevn.gateway.token}",
            },
        },
    )
    sweep = await run_harness_boot_sweep(conn=conn2, trace=sink, workspace=cfg, now_ns=now + 1)
    conn2.close()

    assert sweep.gc_deleted_count == 0
    prompt_ids = {r.run_id for r in sweep.owner_prompt_runs}
    assert "run-b-resume" in prompt_ids
    assert "run-c-resume" in prompt_ids
    assert not sweep.auto_resumed_tier_b

    conn3 = _open_db(db_path)
    rows = conn3.execute(
        "SELECT run_id, tier, status FROM active_run_snapshots ORDER BY run_id",
    ).fetchall()
    conn3.close()
    assert len(rows) == 2
    assert ("run-b-resume", "B", "pending_resume") in rows
    assert ("run-c-resume", "C", "active") in rows


@pytest.mark.asyncio
async def test_tier_b_auto_resume_when_config_enabled(tmp_path: Path) -> None:
    """``gateway.restart.auto_resume_b=true`` classifies tier-B without owner prompt."""
    db_path = tmp_path / "sevn.db"
    now = time.time_ns()
    sink = _ListSink()
    conn = _open_db(db_path)
    await persist_run_snapshot(
        conn=conn,
        row=ActiveRunSnapshotWrite(
            run_id="run-b-auto",
            session_id="sess-b-auto",
            tier="B",
            plan_state={"turn_id": "t", "run_id": "run-b-auto"},
            in_flight_tools=[],
            excerpt="auto",
            status="pending_resume",
            created_at_ns=now,
            updated_at_ns=now,
        ),
        trace=sink,
    )
    conn.commit()
    conn.close()

    conn2 = _open_db(db_path)
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {
                "restart": {"auto_resume_b": True},
                "token": "${SECRET:keychain:sevn.gateway.token}",
            },
        },
    )
    sweep = await sweep_active_run_snapshots(conn=conn2, trace=sink, workspace=cfg, now_ns=now + 1)
    conn2.close()
    assert tuple(r.run_id for r in sweep.auto_resumed_tier_b) == ("run-b-auto",)
    assert not sweep.owner_prompt_runs
