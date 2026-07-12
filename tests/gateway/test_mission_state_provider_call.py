"""Mission state provider.call fan-out tests (lane #1 W2)."""

from __future__ import annotations

from time import time_ns

import pytest

from sevn.agent.tracing.sink import TraceEvent
from sevn.gateway.mission_state import MissionControlState


def _telemetry_event(
    *,
    kind: str,
    session_id: str = "s1",
    attrs: dict[str, object] | None = None,
    status: str = "ok",
) -> TraceEvent:
    start = time_ns()
    return TraceEvent(
        kind=kind,
        span_id="span-telemetry",
        parent_span_id=None,
        session_id=session_id,
        turn_id="t1",
        tier="B",
        ts_start_ns=start,
        ts_end_ns=start + 2_000_000,
        status=status,
        attrs=dict(attrs or {}),
    )


@pytest.mark.asyncio
async def test_provider_call_updates_provider_stats() -> None:
    state = MissionControlState()
    await state.apply_telemetry_trace_event(
        _telemetry_event(
            kind="provider.call",
            attrs={
                "model.id": "anthropic/claude-sonnet-4-6",
                "cost.tokens_in": 10,
                "cost.tokens_out": 5,
                "latency_ms": 12.5,
            },
        ),
    )
    status = state.get_status()
    providers = status["providers"]
    assert "anthropic" in providers
    assert providers["anthropic"]["requests"] >= 1
    assert providers["anthropic"]["tokens"] >= 15


@pytest.mark.asyncio
async def test_channel_start_registers_runtime_health() -> None:
    state = MissionControlState()
    await state.apply_telemetry_trace_event(
        _telemetry_event(kind="channel.telegram.start", session_id=""),
    )
    status = state.get_status()
    channels = status["channels"]
    assert "telegram" in channels
    assert channels["telegram"]["connected"] is True


@pytest.mark.asyncio
async def test_channel_poll_increments_message_count() -> None:
    state = MissionControlState()
    state.register_channel("telegram", adapter_type="telegram")
    await state.apply_telemetry_trace_event(
        _telemetry_event(kind="channel.telegram.poll.cycle", session_id=""),
    )
    status = state.get_status()
    assert status["channels"]["telegram"]["messages"] >= 1
