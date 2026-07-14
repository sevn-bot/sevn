"""Mission Control state from gateway trace events (recovery Wave C1)."""

from __future__ import annotations

import asyncio
from time import time_ns

import pytest

from sevn.agent.tracing.emit import (
    reset_trace_subscribers_for_tests,
    wrap_trace_sink,
)
from sevn.agent.tracing.sink import NullTraceSink, TraceEvent
from sevn.gateway.mission.mission_state import (
    GATEWAY_TRACE_KINDS,
    MissionControlState,
    MissionControlTraceSink,
    create_mission_trace_sink,
    detach_mission_trace_sink,
)


def _trace_event(
    *,
    kind: str,
    session_id: str,
    turn_id: str = "turn-1",
    status: str = "completed",
    attrs: dict[str, object] | None = None,
    ts_end_ns: int | None = None,
) -> TraceEvent:
    start = time_ns()
    end = ts_end_ns if ts_end_ns is not None else start + 1_000_000
    return TraceEvent(
        kind=kind,
        span_id="span-test",
        parent_span_id=None,
        session_id=session_id,
        turn_id=turn_id,
        tier=None,
        ts_start_ns=start,
        ts_end_ns=end,
        status=status,
        attrs=dict(attrs or {}),
    )


@pytest.fixture(autouse=True)
def _clear_trace_subscribers() -> None:
    reset_trace_subscribers_for_tests()
    yield
    reset_trace_subscribers_for_tests()


@pytest.mark.asyncio
async def test_gateway_trace_kinds_subset() -> None:
    assert "gateway.triage.completed" in GATEWAY_TRACE_KINDS
    assert "gateway.executor.b_completed" in GATEWAY_TRACE_KINDS
    assert "gateway.triage.disregard" in GATEWAY_TRACE_KINDS


@pytest.mark.asyncio
async def test_triage_completed_updates_sessions_and_complexity() -> None:
    state = MissionControlState()
    t1 = 1_700_000_000_000_000_000
    t2 = 1_800_000_000_000_000_000
    await state.apply_trace_event(
        _trace_event(
            kind="gateway.triage.completed",
            session_id="s-a",
            attrs={"complexity": "A"},
            ts_end_ns=t1,
        ),
    )
    await state.apply_trace_event(
        _trace_event(
            kind="gateway.triage.completed",
            session_id="s-b",
            attrs={"complexity": "B"},
            ts_end_ns=t2,
        ),
    )
    await state.apply_trace_event(
        _trace_event(
            kind="gateway.triage.completed",
            session_id="s-a",
            turn_id="turn-2",
            attrs={"complexity": "C"},
            ts_end_ns=t2 + 1,
        ),
    )
    metrics = state.get_gateway_metrics()
    assert metrics["total_sessions"] == 2
    assert metrics["complexity_distribution"]["A"] == 1
    assert metrics["complexity_distribution"]["B"] == 1
    assert metrics["complexity_distribution"]["C"] == 1
    assert metrics["gateway_turns"] == 3
    sessions = metrics["sessions"]
    assert sessions["s-a"]["turn_count"] == 2
    assert sessions["s-a"]["last_complexity"] == "C"
    assert sessions["s-a"]["last_activity_at"] == pytest.approx((t2 + 1) / 1_000_000_000)
    assert sessions["s-b"]["last_activity_at"] == pytest.approx(t2 / 1_000_000_000)


@pytest.mark.asyncio
async def test_disregard_and_escalation_counters() -> None:
    state = MissionControlState()
    await state.apply_trace_event(
        _trace_event(kind="gateway.triage.disregard", session_id="s1"),
    )
    await state.apply_trace_event(
        _trace_event(
            kind="gateway.executor.b_completed",
            session_id="s1",
            status="escalated",
        ),
    )
    metrics = state.get_gateway_metrics()
    assert metrics["disregards"] == 1
    assert metrics["escalations"] == 1
    assert metrics["sessions"]["s1"]["disregards"] == 1
    assert metrics["sessions"]["s1"]["escalations"] == 1


@pytest.mark.asyncio
async def test_b_completed_failed_increments_error_rate() -> None:
    state = MissionControlState()
    await state.apply_trace_event(
        _trace_event(
            kind="gateway.triage.completed",
            session_id="s1",
            attrs={"complexity": "B"},
        ),
    )
    await state.apply_trace_event(
        _trace_event(
            kind="gateway.executor.b_completed",
            session_id="s1",
            status="failed",
        ),
    )
    metrics = state.get_gateway_metrics()
    assert metrics["gateway_errors"] == 1
    assert metrics["error_rate"] == pytest.approx(1.0)
    assert metrics["sessions"]["s1"]["errors"] == 1


@pytest.mark.asyncio
async def test_mission_trace_sink_via_emit_fanout() -> None:
    state = MissionControlState()
    mission_sink = create_mission_trace_sink(state)
    primary = wrap_trace_sink(NullTraceSink())
    try:
        await primary.emit(
            _trace_event(
                kind="gateway.triage.completed",
                session_id="ws-1",
                attrs={"complexity": "D"},
            ),
        )
        await primary.emit(
            _trace_event(
                kind="gateway.executor.b_completed",
                session_id="ws-1",
                status="completed",
            ),
        )
    finally:
        detach_mission_trace_sink(mission_sink)

    metrics = state.get_gateway_metrics()
    assert metrics["total_sessions"] == 1
    assert metrics["complexity_distribution"]["D"] == 1


@pytest.mark.asyncio
async def test_mission_trace_sink_emit_direct() -> None:
    state = MissionControlState()
    sink = MissionControlTraceSink(state)
    await sink.emit(
        _trace_event(kind="gateway.triage.disregard", session_id="solo"),
    )
    assert state.get_gateway_metrics()["disregards"] == 1


@pytest.mark.asyncio
async def test_legacy_provider_metrics_still_work() -> None:
    state = MissionControlState()
    state.update_provider("openai", latency_ms=120, tokens=40)
    status = state.get_status()
    assert status["providers"]["openai"]["requests"] == 1
    assert status["providers"]["openai"]["tokens"] == 40


def test_create_mission_trace_sink_registers_subscriber() -> None:
    state = MissionControlState()
    sink = create_mission_trace_sink(state)
    try:
        assert isinstance(sink, MissionControlTraceSink)
    finally:
        detach_mission_trace_sink(sink)


def test_apply_trace_event_sync_from_asyncio() -> None:
    state = MissionControlState()
    asyncio.run(
        state.apply_trace_event(
            _trace_event(
                kind="gateway.triage.completed",
                session_id="x",
                attrs={"complexity": "A"},
            ),
        ),
    )
    assert state.get_gateway_metrics()["total_sessions"] == 1
