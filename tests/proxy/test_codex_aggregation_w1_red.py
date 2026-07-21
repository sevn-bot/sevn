"""PR #52 tooling session-failure RED tests (green after W18)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from loguru import logger as loguru_logger

from sevn.gateway import agent_turn
from sevn.gateway.session_manager import (
    _merge_dispatch_routing_extras,
    _record_dispatch_routing,
    dispatch_routing_for,
)


@pytest.mark.asyncio
async def test_slow_turn_routes_still_working_progress() -> None:
    """Drive ``_schedule_turn_progress_signal`` — not just string-shape of the helper."""
    routed: list[str] = []

    async def _route(*_a: Any, **_k: Any) -> None:
        # Signature: router, channel, user_id, session_id, text, ...
        text = _a[4] if len(_a) > 4 else _k.get("text", "")
        routed.append(str(text))

    l1_state = MagicMock()
    l1_state.progress_task = None
    router = MagicMock()

    with (
        patch.object(agent_turn, "_route_assistant_text", new=_route),
        patch.object(agent_turn, "_TURN_PROGRESS_SIGNAL_DELAY_S", 0.01),
        patch.object(agent_turn, "_cancel_turn_progress_signal", lambda _s: None),
    ):
        await agent_turn._schedule_turn_progress_signal(
            router=router,
            channel="telegram",
            user_id="1",
            session_id="sess-slow",
            route_meta={"chat_id": 1},
            l1_state=l1_state,
        )
        task = getattr(l1_state, "progress_task", None)
        assert task is not None
        await task
    assert routed
    assert any("still" in t.lower() or "working" in t.lower() for t in routed)


def test_classifier_timeout_uses_dispatch_routing_extras() -> None:
    """Drive ``_record_dispatch_routing`` + ``_merge_dispatch_routing_extras`` (production D7)."""
    _record_dispatch_routing(
        "sess-1",
        "corr-1",
        channel="telegram",
        chat_id=1001,
    )
    _merge_dispatch_routing_extras(
        "sess-1",
        "corr-1",
        {"relatedness_classifier_fallback": True},
    )
    routing = dispatch_routing_for("sess-1", "corr-1")
    assert routing["chat_id"] == 1001
    assert routing["channel"] == "telegram"
    assert routing.get("relatedness_classifier_fallback") is True


def test_record_turn_stage_latencies_logs_when_mc_missing() -> None:
    router = MagicMock()
    # Unwired Mission Control — must log so high-latency attribution is not silent.
    router._mission_control_state = None
    captured: list[str] = []
    sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="DEBUG")
    try:
        agent_turn._record_turn_stage_latencies(router, {"upstream": 12_000.0})
    finally:
        loguru_logger.remove(sink_id)
    assert any(
        "mission" in line.lower()
        or "latency" in line.lower()
        or "unwired" in line.lower()
        or "missing" in line.lower()
        for line in captured
    )
