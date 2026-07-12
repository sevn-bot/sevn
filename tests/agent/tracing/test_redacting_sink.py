"""Tests for ``RedactingSink`` — single redaction pass before fan-out."""

from __future__ import annotations

import copy

import pytest

from sevn.agent.tracing.multi_sink import MultiSink
from sevn.agent.tracing.redacting_sink import RedactingSink, TraceRedactionPolicy, redact
from sevn.agent.tracing.sink import TraceEvent


class _RecordingSink:
    """Capture ``emit`` payloads for assertions."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _sample_event(**attrs: object) -> TraceEvent:
    return TraceEvent(
        kind="tool.call",
        span_id="span-1",
        parent_span_id=None,
        session_id="session-1",
        turn_id="turn-1",
        tier="B",
        ts_start_ns=100,
        ts_end_ns=200,
        status="ok",
        attrs=dict(attrs),
    )


@pytest.mark.asyncio
async def test_redacting_sink_fanout_both_sinks_receive_redacted_copy() -> None:
    policy = TraceRedactionPolicy.from_defaults()
    sink_a = _RecordingSink()
    sink_b = _RecordingSink()
    wrapped = RedactingSink(MultiSink([sink_a, sink_b]), policy)

    original_attrs = {
        "api_key": "sk-abcdefghijklmnopqrstuvwxyz123456",
        "note": "ghp_abcdefghijklmnopqrstuvwxyz123456",
        "safe": "visible",
    }
    original = TraceEvent(
        kind="tool.call",
        span_id="span-1",
        parent_span_id=None,
        session_id="session-1",
        turn_id="turn-1",
        tier="B",
        ts_start_ns=100,
        ts_end_ns=200,
        status="ok",
        attrs=original_attrs,
    )
    attrs_before = copy.deepcopy(original.attrs)

    await wrapped.emit(original)

    assert original.attrs == attrs_before
    assert original.attrs["api_key"] == "sk-abcdefghijklmnopqrstuvwxyz123456"

    for recording in (sink_a, sink_b):
        assert len(recording.events) == 1
        received = recording.events[0]
        assert received.attrs["api_key"] == "<redacted>"
        assert received.attrs["note"] == "<redacted>"
        assert received.attrs["safe"] == "visible"
        assert received.span_id == original.span_id
        assert received.kind == original.kind


def test_redact_does_not_mutate_original_attrs() -> None:
    policy = TraceRedactionPolicy.from_defaults()
    raw = {"nested": {"password": "secret-value"}, "token": "plain"}
    event = _sample_event(**raw)
    before = copy.deepcopy(event.attrs)

    redact(event, policy)

    assert event.attrs == before
    assert event.attrs["nested"]["password"] == "secret-value"
