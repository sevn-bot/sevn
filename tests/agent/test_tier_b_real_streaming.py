"""Real SSE streaming for tier-B (`specs/14-executor-tier-b.md` §2.3, `specs/05` §2.3).

Proves the tier-B ``FunctionModel`` consumes ``Transport.complete_stream`` and emits
genuine, monotonically growing token deltas (not one final blob) through the harness
streaming sink — and degrades gracefully to a non-streaming ``complete`` round when the
stream cannot start.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.executors.b_harness import run_b_turn
from sevn.agent.executors.b_types import ResolvedTierBModel, SessionHandle
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import (
    AnthropicMessagesTransport,
    StreamFinal,
    StreamTextDelta,
)
from sevn.config.workspace_config import SecurityWorkspaceConfig, WorkspaceConfig
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from tests.agent.test_b_harness import _base_triage, _make_tick_executor


def _anthropic_text_payload(text: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


class _StreamingAnthropicTransport(AnthropicMessagesTransport):
    """Anthropic transport that streams scripted per-fragment text deltas (no socket)."""

    def __init__(self, fragments: list[str]) -> None:
        super().__init__(proxy_base_url="http://tier-b-real-stream.test.invalid")
        self._fragments = fragments
        self.complete_calls = 0
        self.stream_calls = 0

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        self.complete_calls += 1
        return _anthropic_text_payload("".join(self._fragments))

    async def complete_stream(self, request: dict[str, object]) -> Any:
        self.stream_calls += 1
        for frag in self._fragments:
            yield StreamTextDelta(text=frag)
        yield StreamFinal(response=_anthropic_text_payload("".join(self._fragments)))


class _BrokenStreamAnthropicTransport(AnthropicMessagesTransport):
    """Anthropic transport whose ``complete_stream`` fails before any delta is yielded."""

    def __init__(self, final_text: str) -> None:
        super().__init__(proxy_base_url="http://tier-b-real-stream.test.invalid")
        self._final_text = final_text
        self.complete_calls = 0

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        self.complete_calls += 1
        return _anthropic_text_payload(self._final_text)

    async def complete_stream(self, request: dict[str, object]) -> Any:
        msg = "upstream SSE refused"
        raise RuntimeError(msg)
        yield  # pragma: no cover — marks this an async generator


def _ctx(tmp_path: Path, tool_set: Any) -> ToolContext:
    return ToolContext(
        session_id="s1",
        workspace_path=tmp_path,
        workspace_id="w",
        registry_version=tool_set.registry_version,
        permissions=AllowAllPermissionPolicy(),
        turn_id="t1",
    )


def _ws(tmp_path: Path) -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        workspace_root=str(tmp_path),
        security=SecurityWorkspaceConfig(),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


@pytest.mark.asyncio
async def test_real_deltas_accumulate_monotonically(tmp_path: Path) -> None:
    """The sink is called repeatedly with growing text (real deltas, not one chunk)."""
    exe, tool_set = _make_tick_executor()
    triage = _base_triage(tools=[])
    transport = _StreamingAnthropicTransport(["The ", "answer ", "is ", "42."])
    assert transport.supports_streaming is True
    bundle = ResolvedTierBModel(
        model_id="minimax/MiniMax-M3",
        transport=transport,
        budget=ModelBudget(model_id="minimax/MiniMax-M3", regime=BudgetRegime.PER_TOKEN),
    )
    captured: list[str] = []

    async def _sink(text: str) -> None:
        captured.append(text)

    outcome = await run_b_turn(
        workspace=_ws(tmp_path),
        session=SessionHandle(session_id="s1"),
        turn_id="t1",
        triage=triage,
        incoming_text="what is the answer?",
        tool_set=tool_set,
        body_cache=LoadedBodyCache(capacity=4),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=_ctx(tmp_path, tool_set),
        streaming_sink=_sink,
        streaming_debounce_s=0.0,
    )

    assert outcome.status == "completed"
    assert transport.stream_calls == 1
    assert transport.complete_calls == 0  # genuine streaming, no batch round-trip
    # Multiple sink calls (real deltas), each a prefix-growing accumulation.
    assert len(captured) > 1
    for prev, nxt in pairwise(captured):
        assert nxt.startswith(prev)
        assert len(nxt) >= len(prev)
    assert captured[-1] == "The answer is 42."
    assert outcome.final_messages[-1].text == "The answer is 42."


@pytest.mark.asyncio
async def test_midstream_failure_falls_back_to_complete(tmp_path: Path) -> None:
    """A stream that fails before any delta falls back to ``complete`` and still completes."""
    exe, tool_set = _make_tick_executor()
    triage = _base_triage(tools=[])
    transport = _BrokenStreamAnthropicTransport("Recovered via complete.")
    bundle = ResolvedTierBModel(
        model_id="minimax/MiniMax-M3",
        transport=transport,
        budget=ModelBudget(model_id="minimax/MiniMax-M3", regime=BudgetRegime.PER_TOKEN),
    )
    captured: list[str] = []

    async def _sink(text: str) -> None:
        captured.append(text)

    outcome = await run_b_turn(
        workspace=_ws(tmp_path),
        session=SessionHandle(session_id="s1"),
        turn_id="t1",
        triage=triage,
        incoming_text="hi",
        tool_set=tool_set,
        body_cache=LoadedBodyCache(capacity=4),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=_ctx(tmp_path, tool_set),
        streaming_sink=_sink,
        streaming_debounce_s=0.0,
    )

    assert outcome.status == "completed"
    assert transport.complete_calls == 1  # fallback round-trip happened
    assert outcome.final_messages[-1].text == "Recovered via complete."
    # The fallback still surfaced the answer to the streaming sink.
    assert captured
    assert captured[-1] == "Recovered via complete."
