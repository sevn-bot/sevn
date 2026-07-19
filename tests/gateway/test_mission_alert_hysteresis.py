"""RED suite for Mission Control alert hysteresis (D4; green after W4)."""

from __future__ import annotations

import pytest

from sevn.agent.tracing.sink import TraceEvent
from sevn.gateway.mission.mission_state import MissionControlState


def _gateway_boot_event(*, session_id: str = "boot") -> TraceEvent:
    return TraceEvent(
        kind="gateway.boot",
        span_id="boot-span",
        parent_span_id=None,
        session_id=session_id,
        turn_id="boot",
        tier=None,
        ts_start_ns=1_000_000_000,
        ts_end_ns=2_000_000_000,
        status="completed",
        attrs={},
    )


def _critical_alerts(state: MissionControlState, rule_name: str) -> list[object]:
    return [
        alert
        for alert in state._alerts
        if alert.rule_name == rule_name and alert.severity == "critical"
    ]


def test_single_channel_down_breach_does_not_fire_critical() -> None:
    """D4: one transient ``channel_down`` breach must not page critical."""
    state = MissionControlState()
    state.register_channel("telegram")
    state.update_channel("telegram", connected=False, connection_state="disconnected")
    assert _critical_alerts(state, "channel_down") == []


def test_sustained_channel_down_breaches_fire_critical() -> None:
    """D4: N consecutive ``channel_down`` breaches still escalate to critical."""
    state = MissionControlState()
    state.register_channel("telegram")
    for _ in range(2):
        state.update_channel("telegram", connected=False, connection_state="disconnected")
        assert _critical_alerts(state, "channel_down") == []
    state.update_channel("telegram", connected=False, connection_state="disconnected")
    assert _critical_alerts(state, "channel_down")


@pytest.mark.asyncio
async def test_graceful_gateway_restart_does_not_fire_channel_down_critical() -> None:
    """D4: a graceful restart must not immediately flip ``channel_down`` critical."""
    state = MissionControlState()
    state.register_channel("telegram", adapter_type="telegram")
    await state.apply_trace_event(_gateway_boot_event())
    state.update_channel("telegram", connected=False, connection_state="connecting", reconnect=True)
    assert _critical_alerts(state, "channel_down") == []


def test_single_error_rate_spike_does_not_fire_critical() -> None:
    """D4: one ``high_error_rate`` sample must not page critical."""
    state = MissionControlState()
    state.update_provider("openai", error=True)
    assert _critical_alerts(state, "high_error_rate") == []


def test_sustained_high_error_rate_fires_critical() -> None:
    """D4: sustained ``high_error_rate`` breaches still escalate to critical."""
    state = MissionControlState()
    for _ in range(2):
        state.update_provider("openai", error=True)
        assert _critical_alerts(state, "high_error_rate") == []
    state.update_provider("openai", error=True)
    assert _critical_alerts(state, "high_error_rate")
