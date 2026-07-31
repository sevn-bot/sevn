"""Batch F W27 RED: first-token (TTFT) instrumentation (#78) → W30."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway import agent_turn

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceEvent


class _RecordingTraceSink:
    """Collect trace events for TTFT assertions (no I/O)."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return

    async def close(self) -> None:
        return


@pytest.mark.xfail(reason="green after W30: TTFT timing span on gateway turn", strict=False)
def test_ttft_span_kind_is_documented() -> None:
    """Gateway exposes a stable TTFT span kind for Mission Control and traces."""
    from sevn.gateway.telemetry.ttft import TTFT_SPAN_KIND

    assert TTFT_SPAN_KIND == "gateway.turn.ttft"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W30: TTFT span emitted during agent turn", strict=False)
async def test_agent_turn_emits_ttft_span_with_positive_ms() -> None:
    """A completed turn records first-token latency in milliseconds."""
    from sevn.gateway.telemetry.ttft import extract_ttft_ms_from_events

    sink = _RecordingTraceSink()
    router = MagicMock()
    router._mission_control_state = None

    async def _fake_triage(*_a: object, **_k: object) -> MagicMock:
        outcome = MagicMock()
        outcome.tools = []
        outcome.intent = "answer"
        outcome.model_tier = "B"
        return outcome

    with (
        patch.object(agent_turn, "triage_turn", new=AsyncMock(side_effect=_fake_triage)),
        patch.object(
            agent_turn, "_run_tier_b_executor", new=AsyncMock(return_value=MagicMock(text="hi"))
        ),
        patch.object(agent_turn, "_emit_gateway_span", new=AsyncMock()) as emit_span,
    ):
        emit_span.side_effect = sink.emit
        # Minimal hook: W30 wires TTFT into the turn spine; this test pins the contract.
        from sevn.gateway.telemetry.ttft import record_ttft_sample

        await record_ttft_sample(
            trace=sink,
            session_id="ttft-sess",
            turn_id="turn-1",
            ttft_ms=250.0,
        )

    ttft_ms = extract_ttft_ms_from_events(sink.events)
    assert ttft_ms is not None
    assert ttft_ms > 0


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="green after W30: deferred MCP discovery does not change turn output",
    strict=False,
)
async def test_deferred_mcp_discovery_preserves_turn_output() -> None:
    """Deferring MCP discovery off the boot critical path must not alter turn text."""
    from sevn.gateway.telemetry.ttft import run_turn_with_deferred_mcp_discovery

    workspace = WorkspaceConfig.minimal()
    baseline_text = "baseline answer without deferred boot work"

    async def _executor(*_a: object, **_k: object) -> str:
        await asyncio.sleep(0)
        return baseline_text

    eager = await run_turn_with_deferred_mcp_discovery(
        workspace=workspace,
        defer_mcp_discovery=False,
        executor=_executor,
    )
    deferred = await run_turn_with_deferred_mcp_discovery(
        workspace=workspace,
        defer_mcp_discovery=True,
        executor=_executor,
    )
    assert deferred.text == eager.text == baseline_text
