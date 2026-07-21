"""PR #52 tooling session-failure RED tests (green after W18)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sevn.gateway import agent_turn
from sevn.gateway.session_manager import (
    _merge_dispatch_routing_extras,
    _record_dispatch_routing,
    dispatch_routing_for,
)


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W18: Still working routed on slow turn", strict=False)
async def test_slow_turn_routes_still_working_progress() -> None:
    """Drive ``_schedule_turn_progress_signal`` — not just string-shape of the helper."""
    routed: list[str] = []

    async def _route(*_a: Any, **_k: Any) -> None:
        # Signature: router, channel, user_id, text, ...
        text = _a[3] if len(_a) > 3 else _k.get("text", "")
        routed.append(str(text))

    l1_state = MagicMock()
    l1_state.turn_progress_task = None
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
        # The scheduler stores a task on l1_state; await it if present.
        task = getattr(l1_state, "turn_progress_task", None)
        if task is not None:
            await task
        else:
            await asyncio.sleep(0.05)
    assert routed
    assert any("still" in t.lower() or "working" in t.lower() for t in routed)


@pytest.mark.xfail(reason="green after W18: D7 production routing path", strict=False)
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


@pytest.mark.xfail(reason="green after W18: latency no-op log observable", strict=False)
def test_record_turn_stage_latencies_logs_when_mc_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    router = MagicMock()
    # Unwired Mission Control — today silently returns.
    router._mission_control_state = None
    with caplog.at_level(logging.DEBUG):
        agent_turn._record_turn_stage_latencies(router, {"upstream": 12_000.0})
    assert any(
        "mission" in r.message.lower()
        or "latency" in r.message.lower()
        or "unwired" in r.message.lower()
        or "missing" in r.message.lower()
        for r in caplog.records
    )
