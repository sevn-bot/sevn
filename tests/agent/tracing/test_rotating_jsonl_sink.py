"""Tests for ``RotatingJSONLFileSink`` daily UTC rotation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.agent.tracing.rotating_jsonl_sink import RotatingJSONLFileSink
from sevn.agent.tracing.sink import TraceEvent


def _sample_event(*, kind: str = "test.event") -> TraceEvent:
    return TraceEvent(
        kind=kind,
        span_id="span-1",
        parent_span_id=None,
        session_id="session-1",
        turn_id="turn-1",
        tier=None,
        ts_start_ns=100,
        ts_end_ns=200,
        status="ok",
        attrs={"note": "sample"},
    )


@pytest.mark.asyncio
async def test_rotating_jsonl_sink_two_utc_days_create_two_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    traces_dir = tmp_path / "traces"
    sink = RotatingJSONLFileSink(traces_dir)
    state = {"date": "2026-01-01"}

    monkeypatch.setattr(
        "sevn.agent.tracing.rotating_jsonl_sink._utc_date_str",
        lambda: state["date"],
    )

    await sink.emit(_sample_event(kind="day-one"))
    state["date"] = "2026-01-02"
    await sink.emit(_sample_event(kind="day-two"))

    day_one = traces_dir / "2026-01-01.jsonl"
    day_two = traces_dir / "2026-01-02.jsonl"
    assert day_one.is_file()
    assert day_two.is_file()

    day_one_kinds = [
        json.loads(line)["kind"] for line in day_one.read_text(encoding="utf-8").splitlines()
    ]
    day_two_kinds = [
        json.loads(line)["kind"] for line in day_two.read_text(encoding="utf-8").splitlines()
    ]
    assert day_one_kinds == ["day-one"]
    assert day_two_kinds == ["day-two"]
