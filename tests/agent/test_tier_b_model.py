"""Tests for tier-B FunctionModel boundary: XML tool allowlist filter (W3.2)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.messages import ModelRequest, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo

from sevn.agent.adapters.tier_b_model import build_tier_b_function_model
from sevn.agent.executors.b_types import ResolvedTierBModel
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import AnthropicMessagesTransport


def _info() -> AgentInfo:
    return AgentInfo(
        function_tools=[],
        allow_text_output=True,
        output_tools=[],
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
        instructions=None,
    )


class _FakeAnthropic(AnthropicMessagesTransport):
    """Return a fixed payload regardless of request."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(proxy_base_url="http://test")
        self._payload = payload

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        return dict(self._payload)


def _anthropic_xml_payload(tool_name: str) -> dict[str, Any]:
    """Return an Anthropic response whose text block contains XML tool markup."""
    xml = f'<invoke name="{tool_name}"><parameter name="query">test</parameter></invoke>'
    return {
        "content": [{"type": "text", "text": xml}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "stop_reason": "tool_use",
    }


def _anthropic_mixed_payload(blocked_name: str, allowed_name: str) -> dict[str, Any]:
    """Return a payload with two XML tool calls: one blocked, one allowed."""
    xml = (
        f'<invoke name="{blocked_name}"><parameter name="query">x</parameter></invoke>'
        f'<invoke name="{allowed_name}"><parameter name="file_path">a.py</parameter></invoke>'
    )
    return {
        "content": [{"type": "text", "text": xml}],
        "usage": {"input_tokens": 10, "output_tokens": 8},
        "stop_reason": "tool_use",
    }


@pytest.mark.asyncio
async def test_xml_recovered_unknown_tool_is_dropped_by_allowlist() -> None:
    """A tool recovered from XML that is NOT in allowed_tool_names must be dropped.

    Scenario: MiniMax returns ``<invoke name="find_file">…</invoke>`` in a text
    block.  ``anthropic_completion_to_model_response`` converts this to a
    ``ToolCallPart(tool_name="find_file")``.  With ``allowed_tool_names`` not
    containing ``find_file``, the FunctionModel boundary filter must drop it so
    pydantic-ai never re-sends it to Anthropic as a ``tool_use`` block.
    """
    transport = _FakeAnthropic(_anthropic_xml_payload("find_file"))
    model = build_tier_b_function_model(
        bundle=ResolvedTierBModel(
            model_id="minimax/MiniMax-M3",
            transport=transport,
            budget=ModelBudget(model_id="minimax/MiniMax-M3", regime=BudgetRegime.PER_TOKEN),
        ),
        steer_buffer=None,
        trace=None,
        session_id="s1",
        turn_id="t1",
        provider_round_counter=[0],
        agent="tier_b",
        # find_file is NOT in the allowlist (not bound this turn)
        allowed_tool_names=frozenset({"read", "edit", "write", "request_escalation"}),
    )
    response = await model.function(
        [ModelRequest(parts=[UserPromptPart(content="find the file")])],
        _info(),
    )
    tool_names = [p.tool_name for p in response.parts if isinstance(p, ToolCallPart)]
    assert "find_file" not in tool_names, (
        f"find_file should have been filtered out; got tool_names={tool_names}"
    )
    # No text part should survive either (the raw XML is the only content and was
    # transformed entirely into a ToolCallPart then dropped).
    assert not response.parts or not any(
        isinstance(p, TextPart) and "<invoke" in p.content for p in response.parts
    ), "raw XML markup must not leak into text parts"


@pytest.mark.asyncio
async def test_xml_recovered_allowed_tool_survives_allowlist() -> None:
    """A tool recovered from XML that IS in allowed_tool_names must be kept."""
    transport = _FakeAnthropic(_anthropic_xml_payload("read"))
    model = build_tier_b_function_model(
        bundle=ResolvedTierBModel(
            model_id="minimax/MiniMax-M3",
            transport=transport,
            budget=ModelBudget(model_id="minimax/MiniMax-M3", regime=BudgetRegime.PER_TOKEN),
        ),
        steer_buffer=None,
        trace=None,
        session_id="s1",
        turn_id="t1",
        provider_round_counter=[0],
        agent="tier_b",
        allowed_tool_names=frozenset({"read", "edit", "write", "request_escalation"}),
    )
    response = await model.function(
        [ModelRequest(parts=[UserPromptPart(content="read a file")])],
        _info(),
    )
    tool_names = [p.tool_name for p in response.parts if isinstance(p, ToolCallPart)]
    assert "read" in tool_names, f"read should have been kept in parts; got tool_names={tool_names}"


@pytest.mark.asyncio
async def test_mixed_xml_tools_blocks_unknown_keeps_allowed() -> None:
    """When both a blocked and an allowed tool appear, only the allowed one survives."""
    transport = _FakeAnthropic(_anthropic_mixed_payload("find_file", "read"))
    model = build_tier_b_function_model(
        bundle=ResolvedTierBModel(
            model_id="minimax/MiniMax-M3",
            transport=transport,
            budget=ModelBudget(model_id="minimax/MiniMax-M3", regime=BudgetRegime.PER_TOKEN),
        ),
        steer_buffer=None,
        trace=None,
        session_id="s1",
        turn_id="t1",
        provider_round_counter=[0],
        agent="tier_b",
        allowed_tool_names=frozenset({"read", "edit", "write", "request_escalation"}),
    )
    response = await model.function(
        [ModelRequest(parts=[UserPromptPart(content="find and read a file")])],
        _info(),
    )
    tool_names = [p.tool_name for p in response.parts if isinstance(p, ToolCallPart)]
    assert "find_file" not in tool_names
    assert "read" in tool_names


@pytest.mark.asyncio
async def test_no_allowlist_passes_all_tool_parts_through() -> None:
    """When ``allowed_tool_names`` is ``None``, no filtering is applied (legacy path)."""
    transport = _FakeAnthropic(_anthropic_xml_payload("find_file"))
    model = build_tier_b_function_model(
        bundle=ResolvedTierBModel(
            model_id="minimax/MiniMax-M3",
            transport=transport,
            budget=ModelBudget(model_id="minimax/MiniMax-M3", regime=BudgetRegime.PER_TOKEN),
        ),
        steer_buffer=None,
        trace=None,
        session_id="s1",
        turn_id="t1",
        provider_round_counter=[0],
        agent="tier_b",
        allowed_tool_names=None,  # no filtering
    )
    response = await model.function(
        [ModelRequest(parts=[UserPromptPart(content="find file")])],
        _info(),
    )
    tool_names = [p.tool_name for p in response.parts if isinstance(p, ToolCallPart)]
    # Without the allowlist, find_file must pass through unfiltered.
    assert "find_file" in tool_names
