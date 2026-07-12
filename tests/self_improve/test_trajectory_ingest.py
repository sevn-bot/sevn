"""Trajectory ingest from ``traces.db`` (`specs/33-self-improvement.md` §9 trace join)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sevn.agent.tracing.traces_migrate import apply_traces_migrations
from sevn.config.workspace_config import WorkspaceConfig
from sevn.self_improve.trajectories.ingest import (
    ingest_trajectory_fact_for_turn,
    ingest_trajectory_facts_from_traces,
    trajectory_reconciliation_rate,
)
from sevn.self_improve.trajectories.runner import run_trajectory_ingest
from sevn.self_improve.trajectories.scheduler import (
    TRAJECTORY_INGEST_CRON_JOB_ID,
    read_last_trajectory_ingest_ts_ns,
    reconcile_trajectory_ingest_cron_job,
    run_scheduled_trajectory_ingest,
    write_last_trajectory_ingest_ts_ns,
)
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout


def _insert_trace(
    conn: sqlite3.Connection,
    *,
    span_id: str,
    session_id: str,
    turn_id: str,
    kind: str,
    tier: str = "B",
    ts_start_ns: int,
    attrs: dict[str, object] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO trace_events (
            span_id, parent_span_id, session_id, turn_id, tier, kind,
            ts_start_ns, ts_end_ns, status, attrs_json
        ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 'ok', ?)""",
        (
            span_id,
            session_id,
            turn_id,
            tier,
            kind,
            ts_start_ns,
            ts_start_ns + 1,
            json.dumps(attrs or {}),
        ),
    )


@pytest.fixture
def trace_dbs(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    """In-memory ``sevn.db`` plus on-disk ``traces.db`` with migrations applied."""
    sevn_conn = sqlite3.connect(":memory:")
    apply_migrations(sevn_conn)
    traces_path = tmp_path / "traces.db"
    tconn = sqlite3.connect(traces_path)
    apply_traces_migrations(tconn)
    tconn.close()
    yield sevn_conn, traces_path
    sevn_conn.close()


def test_trajectory_ingest_reconciliation_at_least_95_percent(
    trace_dbs: tuple[sqlite3.Connection, Path],
) -> None:
    """Fixture tool spans reconcile to ``trajectory_fact`` at ≥95% (spec §9)."""
    sevn_conn, traces_path = trace_dbs
    tconn = sqlite3.connect(traces_path)
    try:
        for idx in range(20):
            turn_id = f"turn-{idx:02d}"
            session_id = "sess-fixture"
            triage_attrs = {
                "intent": "chat",
                "complexity": "B",
                "budget_regime": "SUBSCRIPTION",
                "model_id": "openai:gpt-4o-mini",
                "confidence": 0.9,
                "channel": "web",
            }
            _insert_trace(
                tconn,
                span_id=f"triage-{idx}",
                session_id=session_id,
                turn_id=turn_id,
                kind="triage.complete",
                ts_start_ns=1_000 + idx * 10,
                attrs=triage_attrs,
            )
            _insert_trace(
                tconn,
                span_id=f"tool-{idx}",
                session_id=session_id,
                turn_id=turn_id,
                kind="tool.invoke",
                ts_start_ns=1_001 + idx * 10,
                attrs={"name": "read_file"},
            )
        tconn.commit()
    finally:
        tconn.close()

    result = ingest_trajectory_facts_from_traces(sevn_conn, traces_path)
    assert result.rows_upserted == 20
    rate = trajectory_reconciliation_rate(sevn_conn, traces_path)
    assert rate >= 0.95

    row = sevn_conn.execute(
        "SELECT intent, tier, budget_regime, model_id, signals_json FROM trajectory_fact WHERE turn_id = ?",
        ("turn-00",),
    ).fetchone()
    assert row is not None
    assert row[0] == "chat"
    assert row[1] == "B"
    assert row[2] == "SUBSCRIPTION"
    signals = json.loads(str(row[4]))
    assert len(signals["tools"]) == 1
    assert signals["tools"][0]["kind"] == "tool.invoke"


def test_trajectory_ingest_tool_only_turn(trace_dbs: tuple[sqlite3.Connection, Path]) -> None:
    """Tool spans without triage still produce a ``trajectory_fact`` row."""
    sevn_conn, traces_path = trace_dbs
    tconn = sqlite3.connect(traces_path)
    try:
        _insert_trace(
            tconn,
            span_id="tool-only",
            session_id="sess-tool",
            turn_id="turn-tool-only",
            kind="tool.after",
            tier="C",
            ts_start_ns=500,
            attrs={"name": "grep"},
        )
        tconn.commit()
    finally:
        tconn.close()

    ingest_trajectory_facts_from_traces(sevn_conn, traces_path)
    rate = trajectory_reconciliation_rate(sevn_conn, traces_path)
    assert rate == 1.0
    row = sevn_conn.execute(
        "SELECT tier, signals_json FROM trajectory_fact WHERE turn_id = ?",
        ("turn-tool-only",),
    ).fetchone()
    assert row is not None
    assert row[0] == "C"


def test_ingest_trajectory_fact_for_turn_single(
    trace_dbs: tuple[sqlite3.Connection, Path],
) -> None:
    """Single-turn ingest filters on ``trace_events.turn_id``."""
    sevn_conn, traces_path = trace_dbs
    tconn = sqlite3.connect(traces_path)
    try:
        for turn_id in ("turn-a", "turn-b"):
            _insert_trace(
                tconn,
                span_id=f"triage-{turn_id}",
                session_id="sess",
                turn_id=turn_id,
                kind="triage.complete",
                ts_start_ns=100 if turn_id == "turn-a" else 200,
                attrs={"intent": "chat", "complexity": "B", "channel": "web"},
            )
        tconn.commit()
    finally:
        tconn.close()

    result = ingest_trajectory_fact_for_turn(sevn_conn, traces_path, turn_id="turn-a")
    assert result.rows_upserted == 1
    rows = sevn_conn.execute("SELECT turn_id FROM trajectory_fact").fetchall()
    assert [str(row[0]) for row in rows] == ["turn-a"]


def test_ingest_since_ns_incremental(trace_dbs: tuple[sqlite3.Connection, Path]) -> None:
    """Incremental ingest respects ``since_ns`` lower bound."""
    sevn_conn, traces_path = trace_dbs
    tconn = sqlite3.connect(traces_path)
    try:
        _insert_trace(
            tconn,
            span_id="old",
            session_id="sess",
            turn_id="turn-old",
            kind="tool.invoke",
            ts_start_ns=100,
            attrs={"name": "read"},
        )
        _insert_trace(
            tconn,
            span_id="new",
            session_id="sess",
            turn_id="turn-new",
            kind="tool.invoke",
            ts_start_ns=500,
            attrs={"name": "grep"},
        )
        tconn.commit()
    finally:
        tconn.close()

    result = ingest_trajectory_facts_from_traces(sevn_conn, traces_path, since_ns=400)
    assert result.rows_upserted == 1
    row = sevn_conn.execute(
        "SELECT turn_id FROM trajectory_fact WHERE turn_id = ?",
        ("turn-new",),
    ).fetchone()
    assert row is not None


def test_reconcile_trajectory_ingest_cron_job_inserts_row() -> None:
    """Cron reconcile mirrors default trajectories config into SQLite."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    reconcile_trajectory_ingest_cron_job(conn, WorkspaceConfig.minimal())
    row = conn.execute(
        "SELECT job_id, cron_expr, payload_template FROM trigger_cron_jobs WHERE job_id = ?",
        (TRAJECTORY_INGEST_CRON_JOB_ID,),
    ).fetchone()
    assert row is not None
    assert row[1] == "0 4 * * *"
    assert row[2] == "sevn_self_improve_trajectory_ingest"
    conn.close()


def test_run_scheduled_trajectory_ingest_updates_watermark(
    tmp_path: Path,
) -> None:
    """Cron backfill advances ``last_trajectory_ingest_ts_ns`` watermark."""
    sevn_conn = sqlite3.connect(":memory:")
    apply_migrations(sevn_conn)
    layout = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    dot_sevn = layout.dot_sevn
    dot_sevn.mkdir(parents=True)
    traces_path = dot_sevn / "traces.db"
    tconn = sqlite3.connect(traces_path)
    apply_traces_migrations(tconn)
    _insert_trace(
        tconn,
        span_id="cron-span",
        session_id="sess",
        turn_id="turn-cron",
        kind="tool.invoke",
        ts_start_ns=900,
        attrs={"name": "read"},
    )
    tconn.commit()
    tconn.close()

    write_last_trajectory_ingest_ts_ns(sevn_conn, 800)
    run_scheduled_trajectory_ingest(sevn_conn, layout, WorkspaceConfig.minimal())
    assert read_last_trajectory_ingest_ts_ns(sevn_conn) == 900
    row = sevn_conn.execute(
        "SELECT turn_id FROM trajectory_fact WHERE turn_id = ?",
        ("turn-cron",),
    ).fetchone()
    assert row is not None
    sevn_conn.close()


def test_run_trajectory_ingest_via_layout(tmp_path: Path) -> None:
    """Shared runner resolves ``traces.db`` from workspace layout."""
    sevn_conn = sqlite3.connect(":memory:")
    apply_migrations(sevn_conn)
    layout = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    dot_sevn = layout.dot_sevn
    dot_sevn.mkdir(parents=True)
    traces_path = dot_sevn / "traces.db"
    tconn = sqlite3.connect(traces_path)
    apply_traces_migrations(tconn)
    _insert_trace(
        tconn,
        span_id="runner-span",
        session_id="sess",
        turn_id="turn-runner",
        kind="triage.complete",
        ts_start_ns=50,
        attrs={"intent": "chat", "complexity": "C", "channel": "telegram"},
    )
    tconn.commit()
    tconn.close()

    result = run_trajectory_ingest(sevn_conn, layout, turn_id="turn-runner")
    assert result is not None
    assert result.rows_upserted == 1
    sevn_conn.close()
