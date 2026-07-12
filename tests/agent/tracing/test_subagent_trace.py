"""Tests for sub-agent OTel spans and mission telemetry (W5)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExportResult

from sevn.agent.subagents.registry import SubAgentRegistry
from sevn.agent.subagents.supervisor import SubAgentSpec, SubAgentSupervisor
from sevn.agent.tracing.emit import reset_trace_subscribers_for_tests
from sevn.agent.tracing.otel_pipeline import reset_otel_pipeline_for_tests
from sevn.agent.tracing.sink import NullTraceSink, TraceEvent, trace_sink_scope
from sevn.agent.tracing.subagent_trace import (
    SubAgentPrometheusCounts,
    bind_subagent_turn_context,
    build_subagent_trace_hook,
    reset_subagent_trace_for_tests,
)
from sevn.agent.tracing.trace_event_bridge import TraceEventOtelBridge, set_trace_event_bridge
from sevn.gateway.mission_state import MissionControlState
from sevn.gateway.mission_trace_sink import create_mission_trace_sink, detach_mission_trace_sink
from sevn.gateway.prometheus_metrics import render_gateway_metrics


class _RecordingSpanExporter:
    """Capture exported spans for assertions."""

    def __init__(self) -> None:
        self.spans: list[Any] = []

    def export(self, spans: Any) -> SpanExportResult:
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        _ = timeout_millis
        return True


@pytest.fixture(autouse=True)
def _reset_trace_state() -> None:
    reset_otel_pipeline_for_tests()
    reset_subagent_trace_for_tests()
    reset_trace_subscribers_for_tests()
    set_trace_event_bridge(None)
    yield
    reset_otel_pipeline_for_tests()
    reset_subagent_trace_for_tests()
    reset_trace_subscribers_for_tests()
    set_trace_event_bridge(None)


@pytest.mark.asyncio
async def test_two_level_run_emits_parented_subagent_spans() -> None:
    reset_otel_pipeline_for_tests()
    exporter = _RecordingSpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(
        __import__(
            "opentelemetry.sdk.trace.export",
            fromlist=["SimpleSpanProcessor"],
        ).SimpleSpanProcessor(exporter),
    )
    bridge = TraceEventOtelBridge(tracer=provider.get_tracer("test"))
    set_trace_event_bridge(bridge)

    turn_span_id = "turn-root"
    await bridge.emit(
        TraceEvent(
            kind="gateway.turn.start",
            span_id=turn_span_id,
            parent_span_id=None,
            session_id="sess",
            turn_id="turn-1",
            tier=None,
            ts_start_ns=100,
            ts_end_ns=100,
            status="started",
            attrs={},
        ),
    )

    registry = SubAgentRegistry()
    registry.wire_trace(build_subagent_trace_hook(registry))
    bind_subagent_turn_context(turn_id="turn-1", turn_span_id=turn_span_id)

    l1 = await registry.register(
        level=1,
        role="tier_b",
        session_id="sess",
        channel="telegram",
        task_summary="parent task",
    )
    await registry.mark_running(l1.id)
    l2 = await registry.register(
        level=2,
        role="tier_b",
        parent_id=l1.id,
        session_id="sess",
        channel="telegram",
        task_summary="child task",
    )
    await registry.mark_running(l2.id)
    await registry.mark_done(l2.id)
    await registry.mark_done(l1.id)
    provider.force_flush()

    subagent_spans = [span for span in exporter.spans if span.name == "sevn.subagent"]
    assert len(subagent_spans) == 2
    child = next(span for span in subagent_spans if span.attributes.get("sevn.subagent.level") == 2)
    parent = next(
        span for span in subagent_spans if span.attributes.get("sevn.subagent.level") == 1
    )
    assert child.parent is not None
    assert parent.parent is not None
    assert child.attributes.get("sevn.subagent.id") == l2.id
    assert parent.attributes.get("sevn.subagent.id") == l1.id


@pytest.mark.asyncio
async def test_mission_sink_records_subagent_telemetry_counts() -> None:
    state = MissionControlState()
    mission_sink = create_mission_trace_sink(state)
    try:
        with trace_sink_scope(NullTraceSink()):
            registry = SubAgentRegistry()
            registry.wire_trace(build_subagent_trace_hook(registry))
            run = await registry.register(
                level=1,
                role="tier_b",
                session_id="sess-1",
                channel="telegram",
                task_summary="demo",
            )
            await registry.mark_running(run.id)
            await registry.mark_done(run.id)
    finally:
        detach_mission_trace_sink(mission_sink)

    metrics = state.get_gateway_metrics()
    assert metrics["subagents_running"].get("1:tier_b", 0) == 0
    assert metrics["subagents_total"]["done"] == 1
    session = metrics["sessions"]["sess-1"]
    assert session["subagents_total_by_status"]["done"] == 1
    feed = state.get_activity_feed()
    assert any(row["type"] == "subagent" for row in feed)


@pytest.mark.asyncio
async def test_supervisor_kill_emits_subagent_killed_telemetry() -> None:
    captured: list[TraceEvent] = []

    class _CaptureSink(NullTraceSink):
        async def emit(self, event: TraceEvent) -> None:
            captured.append(event)

    state = MissionControlState()
    mission_sink = create_mission_trace_sink(state)
    try:
        with trace_sink_scope(_CaptureSink()):
            registry = SubAgentRegistry()
            registry.wire_trace(build_subagent_trace_hook(registry))
            supervisor = SubAgentSupervisor(registry)

            async def _slow() -> None:
                await asyncio.sleep(30)

            handle = await supervisor.spawn(
                SubAgentSpec(
                    level=1,
                    role="tier_b",
                    body=_slow,
                    session_id="s",
                    channel="c",
                    task_summary="t",
                ),
            )
            assert hasattr(handle, "id")
            await supervisor.kill(handle.id)
    finally:
        detach_mission_trace_sink(mission_sink)

    kinds = [event.kind for event in captured]
    assert "subagent_killed" in kinds
    assert state.get_gateway_metrics()["subagents_total"]["killed"] == 1


def test_prometheus_render_includes_subagent_series() -> None:
    prom = SubAgentPrometheusCounts()
    prom.running[(1, "tier_b")] = 2
    prom.running[(2, "tier_b")] = 1
    prom.total_by_status["done"] = 3
    prom.total_by_status["killed"] = 1
    body = render_gateway_metrics(
        subagents_running=prom.running,
        subagents_total=prom.total_by_status,
    )
    assert 'sevn_subagents_running{level="1",role="tier_b"} 2' in body
    assert 'sevn_subagents_running{level="2",role="tier_b"} 1' in body
    assert 'sevn_subagents_total{status="done"} 3' in body
    assert 'sevn_subagents_total{status="killed"} 1' in body
