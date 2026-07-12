"""Tests for SQLite trace sink."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sevn.agent.tracing import SQLiteSink, TraceEvent


@pytest.mark.asyncio
async def test_sqlite_sink_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "traces.db"
    sink = SQLiteSink(db)
    event = TraceEvent(
        kind="tool.call",
        span_id="s1",
        parent_span_id=None,
        session_id="se",
        turn_id="tu",
        tier="B",
        ts_start_ns=10,
        ts_end_ns=20,
        status="ok",
        attrs={"tool": "echo"},
    )
    await sink.emit(event)
    await sink.close()
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT kind, session_id, turn_id, attrs_json FROM trace_events WHERE span_id = ?",
            ("s1",),
        ).fetchone()
        assert row is not None
        assert row[0] == "tool.call"
        assert row[1] == "se"
        assert row[2] == "tu"
        assert '"tool"' in row[3]
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_sqlite_sink_upsert_same_span(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    sink = SQLiteSink(db)
    base = dict(
        kind="llm",
        span_id="same",
        parent_span_id=None,
        session_id="s",
        turn_id="t",
        tier="A",
        ts_start_ns=1,
        ts_end_ns=None,
        status="pending",
        attrs={},
    )
    await sink.emit(TraceEvent(**base))
    await sink.emit(
        TraceEvent(
            **{**base, "ts_end_ns": 99, "status": "ok", "attrs": {"done": True}},
        ),
    )
    await sink.close()
    conn = sqlite3.connect(str(db))
    try:
        ts_end, st, aj = conn.execute(
            "SELECT ts_end_ns, status, attrs_json FROM trace_events WHERE span_id = ?",
            ("same",),
        ).fetchone()
        assert ts_end == 99
        assert st == "ok"
        assert "done" in aj
    finally:
        conn.close()
