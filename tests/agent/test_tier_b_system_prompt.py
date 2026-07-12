"""Tier-B system prompt projection to Anthropic/OpenAI wire (recovery Wave A fix)."""

from __future__ import annotations

import pytest
from pydantic_ai.messages import ModelRequest, SystemPromptPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo

from sevn.agent.adapters.tier_b_model import (
    build_tier_b_function_model,
    tier_b_system_prompt_text,
)
from sevn.agent.executors.b_types import ResolvedTierBModel
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import AnthropicMessagesTransport


def _agent_info(*, instructions: str | None = "tool doc") -> AgentInfo:
    return AgentInfo(
        function_tools=[],
        allow_text_output=True,
        output_tools=[],
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
        instructions=instructions,
    )


def test_tier_b_system_prompt_text_merges_persona_and_instructions() -> None:
    msgs = [
        ModelRequest(parts=[SystemPromptPart(content="Name: Sevn")]),
        ModelRequest(parts=[UserPromptPart(content="hi")]),
    ]
    out = tier_b_system_prompt_text(msgs, _agent_info(instructions="Ask their name."))
    assert out is not None
    assert "Name: Sevn" in out
    assert "Ask their name." in out


@pytest.mark.asyncio
async def test_anthropic_complete_includes_system_from_persona() -> None:
    captured: dict[str, object] = {}

    class _CaptureTransport(AnthropicMessagesTransport):
        async def complete(self, request: dict[str, object]) -> dict[str, object]:
            captured.update(request)
            return {
                "content": [{"type": "text", "text": "I am Sevn."}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }

    transport = _CaptureTransport(proxy_base_url="http://tier-b-sys.test")
    model = build_tier_b_function_model(
        bundle=ResolvedTierBModel(
            model_id="minimax/MiniMax-M2.7",
            transport=transport,
            budget=ModelBudget(model_id="minimax/MiniMax-M2.7", regime=BudgetRegime.FREE_LOCAL),
        ),
        steer_buffer=None,
        trace=None,
        session_id="s1",
        turn_id="t1",
        provider_round_counter=[0],
    )
    msgs = [
        ModelRequest(
            parts=[
                SystemPromptPart(content="You are Sevn, not MiniMax."),
                UserPromptPart(content="who are you?"),
            ],
        ),
    ]
    info = _agent_info(instructions="Follow BOOTSTRAP.md and ask the user's name.")
    await model.function(msgs, info)
    system = captured.get("system")
    assert isinstance(system, str)
    assert "Sevn" in system
    assert "BOOTSTRAP" in system
    assert "MiniMax" not in system or "not MiniMax" in system
