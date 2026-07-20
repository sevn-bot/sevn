"""Tracing Option-A bundle (`specs/04-tracing.md` §10.7).

Covers:
    * ``attrs_json`` 64 KiB size cap (truncate-with-marker).
    * FTS5 search over ``trace_events``.
    * Idempotent hourly rollup writer.
    * TTL purge of old ``trace_events`` + stale rollups.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sevn.agent.tracing import (
    SQLiteSink,
    TraceEvent,
    purge_trace_events_ttl,
    write_hourly_rollups,
)
from sevn.agent.tracing.sqlite_sink import cap_attrs_json
from sevn.agent.tracing.traces_maintenance import HOUR_NS
from sevn.config.defaults import TRACE_ATTRS_JSON_MAX_BYTES


def _event(
    *,
    span_id: str,
    kind: str = "tool.invoke",
    session_id: str = "se",
    turn_id: str = "tu",
    ts_start_ns: int = 1,
    ts_end_ns: int | None = 2,
    status: str = "ok",
    attrs: dict[str, object] | None = None,
) -> TraceEvent:
    return TraceEvent(
        kind=kind,
        span_id=span_id,
        parent_span_id=None,
        session_id=session_id,
        turn_id=turn_id,
        tier="B",
        ts_start_ns=ts_start_ns,
        ts_end_ns=ts_end_ns,
        status=status,
        attrs=attrs or {},
    )


def test_cap_attrs_json_passthrough_under_cap() -> None:
    payload = '{"hello": "world"}'
    assert cap_attrs_json(payload) == payload


def test_cap_attrs_json_truncates_with_marker() -> None:
    big = json.dumps({"x": "a" * (TRACE_ATTRS_JSON_MAX_BYTES + 1)})
    out = cap_attrs_json(big)
    obj = json.loads(out)
    assert obj == {
        "_truncated": True,
        "_original_bytes": len(big.encode("utf-8")),
        "_truncated_keys": ["x"],
    }
    assert len(out.encode("utf-8")) < TRACE_ATTRS_JSON_MAX_BYTES


@pytest.mark.asyncio
async def test_sqlite_sink_truncates_oversized_attrs_json(tmp_path: Path) -> None:
    db = tmp_path / "traces.db"
    sink = SQLiteSink(db)
    huge_value = "x" * (TRACE_ATTRS_JSON_MAX_BYTES + 1024)
    await sink.emit(_event(span_id="big", attrs={"blob": huge_value}))
    await sink.close()

    conn = sqlite3.connect(str(db))
    try:
        (aj,) = conn.execute(
            "SELECT attrs_json FROM trace_events WHERE span_id = ?", ("big",)
        ).fetchone()
    finally:
        conn.close()
    obj = json.loads(aj)
    assert obj["_truncated"] is True
    assert obj["_original_bytes"] >= TRACE_ATTRS_JSON_MAX_BYTES


@pytest.mark.asyncio
async def test_fts5_search_matches_kind_and_attrs(tmp_path: Path) -> None:
    db = tmp_path / "traces.db"
    sink = SQLiteSink(db)
    await sink.emit(_event(span_id="a1", kind="tool.invoke", attrs={"tool": "ripgrep"}))
    await sink.emit(_event(span_id="a2", kind="gateway.route_incoming", attrs={"channel": "tg"}))
    await sink.close()

    conn = sqlite3.connect(str(db))
    try:
        # FTS query against the virtual table — kind match.
        ripgrep_rows = conn.execute(
            "SELECT span_id FROM trace_events_fts "
            "JOIN trace_events ON trace_events.rowid = trace_events_fts.rowid "
            "WHERE trace_events_fts MATCH ?",
            ("ripgrep",),
        ).fetchall()
        assert [r[0] for r in ripgrep_rows] == ["a1"]

        # FTS query against the virtual table — kind token match.
        kind_rows = conn.execute(
            "SELECT span_id FROM trace_events_fts "
            "JOIN trace_events ON trace_events.rowid = trace_events_fts.rowid "
            "WHERE trace_events_fts MATCH ?",
            ("gateway",),
        ).fetchall()
        assert [r[0] for r in kind_rows] == ["a2"]
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_hourly_rollups_idempotent_and_bucketed(tmp_path: Path) -> None:
    db = tmp_path / "traces.db"
    sink = SQLiteSink(db)
    # Anchor far in the past so both buckets are fully elapsed.
    bucket_a = (1_700_000_000_000_000_000 // HOUR_NS) * HOUR_NS
    bucket_b = bucket_a + HOUR_NS
    now_ns = bucket_b + 2 * HOUR_NS  # two buckets back lie inside the lookback window.

    await sink.emit(
        _event(span_id="s1", ts_start_ns=bucket_a + 10, ts_end_ns=bucket_a + 110, status="ok")
    )
    await sink.emit(
        _event(span_id="s2", ts_start_ns=bucket_a + 20, ts_end_ns=bucket_a + 220, status="error")
    )
    await sink.emit(
        _event(span_id="s3", ts_start_ns=bucket_b + 1, ts_end_ns=bucket_b + 51, status="ok")
    )
    await sink.close()

    n1 = write_hourly_rollups(db, lookback_hours=4, now_ns=now_ns)
    n2 = write_hourly_rollups(db, lookback_hours=4, now_ns=now_ns)
    assert n1 == n2  # idempotent — same number of rows upserted.

    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT hour_bucket_ns, kind, event_count, error_count, max_duration_ns "
            "FROM trace_rollups_hourly ORDER BY hour_bucket_ns, kind"
        ).fetchall()
    finally:
        conn.close()
    # Two buckets, one kind each.
    assert len(rows) == 2
    (
        (a_bucket, a_kind, a_count, a_errs, a_max),
        (b_bucket, _b_kind, b_count, _b_errs, _b_max),
    ) = rows
    assert a_bucket == bucket_a
    assert a_kind == "tool.invoke"
    assert a_count == 2
    assert a_errs == 1
    assert a_max == 200  # s2 duration: 220 - 20
    assert b_bucket == bucket_b
    assert b_count == 1


@pytest.mark.asyncio
async def test_ttl_purge_drops_old_events_keeps_recent(tmp_path: Path) -> None:
    db = tmp_path / "traces.db"
    sink = SQLiteSink(db)
    now_ns = 10 * 24 * HOUR_NS  # arbitrary baseline 10 days in.
    day_ns = 24 * HOUR_NS
    old_ts = now_ns - 60 * day_ns
    recent_ts = now_ns - 1 * day_ns
    await sink.emit(_event(span_id="old", ts_start_ns=old_ts, ts_end_ns=old_ts + 10))
    await sink.emit(_event(span_id="new", ts_start_ns=recent_ts, ts_end_ns=recent_ts + 10))
    await sink.close()

    deleted = purge_trace_events_ttl(db, ttl_days=30, now_ns=now_ns)
    assert deleted == 1

    conn = sqlite3.connect(str(db))
    try:
        remaining = {row[0] for row in conn.execute("SELECT span_id FROM trace_events").fetchall()}
    finally:
        conn.close()
    assert remaining == {"new"}


def test_purge_and_rollups_tolerate_missing_db(tmp_path: Path) -> None:
    db = tmp_path / "no-such.db"
    assert purge_trace_events_ttl(db, ttl_days=30) == 0
    assert write_hourly_rollups(db) == 0
