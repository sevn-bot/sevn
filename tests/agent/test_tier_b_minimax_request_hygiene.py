"""W10: MiniMax anthropic-wire request param hygiene (D2).

Asserts ``tool_choice``, ``top_k`` drop, optional ``thinking``, and ``metadata``
on MiniMax requests built by ``build_tier_b_function_model``; non-MiniMax anthropic
models stay unaffected for thinking/metadata/top_k stripping.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo
from pydantic_ai.tools import ToolDefinition as PAToolDefinition

from sevn.agent.adapters.tier_b_model import (
    TriagerBoundToolChoiceContext,
    build_tier_b_function_model,
)
from sevn.agent.executors.b_types import ResolvedTierBModel
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import AnthropicMessagesTransport
from sevn.config.llm_params import LLM_PARAMS_FILENAME


def _info(*, with_tools: bool = False) -> AgentInfo:
    tools: list[PAToolDefinition] = []
    if with_tools:
        tools.append(
            PAToolDefinition(
                name="read",
                description="Read a file",
                parameters_json_schema={"type": "object", "properties": {}},
            )
        )
    return AgentInfo(
        function_tools=tools,
        allow_text_output=True,
        output_tools=[],
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
        instructions=None,
    )


class _CapturingAnthropic(AnthropicMessagesTransport):
    captured: dict[str, object]

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        self.captured = dict(request)
        return {
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }


@pytest.mark.asyncio
async def test_minimax_anthropic_request_hygiene_with_tools_and_metadata() -> None:
    transport = _CapturingAnthropic(proxy_base_url="http://test")
    model = build_tier_b_function_model(
        bundle=ResolvedTierBModel(
            model_id="minimax/MiniMax-M2",
            transport=transport,
            budget=ModelBudget(model_id="minimax/MiniMax-M2", regime=BudgetRegime.PER_TOKEN),
        ),
        steer_buffer=None,
        trace=None,
        session_id="sess-1",
        turn_id="turn-1",
        provider_round_counter=[0],
        agent="tier_b",
        user_id="user-42",
        channel="telegram",
        workspace_id="ws-1",
        executor_tier="B",
    )
    await model.function(
        [ModelRequest(parts=[UserPromptPart(content="hi")])],
        _info(with_tools=True),
    )
    req = transport.captured
    # Anthropic wire requires the object form; the bare OpenAI string "auto"
    # 400s on MiniMax's Anthropic-compatible endpoint (regression guard).
    assert req["tool_choice"] == {"type": "auto"}
    assert "top_k" not in req
    assert req["temperature"] == pytest.approx(1.0)
    assert req["top_p"] == pytest.approx(0.95)
    assert "thinking" not in req
    metadata = req["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["session_id"] == "sess-1"
    assert metadata["turn_id"] == "turn-1"
    assert metadata["user_id"] == "user-42"
    assert metadata["channel"] == "telegram"
    assert metadata["workspace_id"] == "ws-1"
    assert metadata["agent"] == "tier_b"
    assert metadata["executor_tier"] == "B"


@pytest.mark.asyncio
async def test_minimax_thinking_enabled_from_workspace_config(tmp_path: Path) -> None:
    (tmp_path / LLM_PARAMS_FILENAME).write_text(
        json.dumps(
            {
                "tier_b": {
                    "minimax_thinking": {"enabled": True, "type": "enabled", "budget_tokens": 2048},
                }
            }
        ),
        encoding="utf-8",
    )
    transport = _CapturingAnthropic(proxy_base_url="http://test")
    model = build_tier_b_function_model(
        bundle=ResolvedTierBModel(
            model_id="minimax/MiniMax-M2",
            transport=transport,
            budget=ModelBudget(model_id="minimax/MiniMax-M2", regime=BudgetRegime.PER_TOKEN),
        ),
        steer_buffer=None,
        trace=None,
        session_id="s1",
        turn_id="t1",
        provider_round_counter=[0],
        agent="tier_b",
        content_root=tmp_path,
    )
    await model.function([ModelRequest(parts=[UserPromptPart(content="hi")])], _info())
    req = transport.captured
    assert req["thinking"] == {"type": "enabled", "budget_tokens": 2048}


@pytest.mark.asyncio
async def test_triager_minimax_never_sends_thinking_even_when_config_enabled(
    tmp_path: Path,
) -> None:
    (tmp_path / LLM_PARAMS_FILENAME).write_text(
        json.dumps({"tier_b": {"minimax_thinking": {"enabled": True, "type": "adaptive"}}}),
        encoding="utf-8",
    )
    transport = _CapturingAnthropic(proxy_base_url="http://test")
    model = build_tier_b_function_model(
        bundle=ResolvedTierBModel(
            model_id="minimax/MiniMax-M2",
            transport=transport,
            budget=ModelBudget(model_id="minimax/MiniMax-M2", regime=BudgetRegime.PER_TOKEN),
        ),
        steer_buffer=None,
        trace=None,
        session_id="triager",
        turn_id="triager",
        provider_round_counter=[0],
        agent="triager",
        content_root=tmp_path,
    )
    await model.function([ModelRequest(parts=[UserPromptPart(content="hi")])], _info())
    req = transport.captured
    assert "tool_choice" not in req
    assert "thinking" not in req
    assert "metadata" not in req
    assert "top_k" not in req


@pytest.mark.asyncio
async def test_non_minimax_anthropic_keeps_top_k_and_skips_minimax_extras() -> None:
    transport = _CapturingAnthropic(proxy_base_url="http://test")
    model = build_tier_b_function_model(
        bundle=ResolvedTierBModel(
            model_id="anthropic:claude-3-5-sonnet",
            transport=transport,
            budget=ModelBudget(
                model_id="anthropic:claude-3-5-sonnet",
                regime=BudgetRegime.PER_TOKEN,
            ),
        ),
        steer_buffer=None,
        trace=None,
        session_id="s1",
        turn_id="t1",
        provider_round_counter=[0],
        agent="tier_b",
        user_id="u1",
        channel="webchat",
    )
    await model.function(
        [ModelRequest(parts=[UserPromptPart(content="hi")])],
        _info(with_tools=True),
    )
    req = transport.captured
    assert "tool_choice" not in req
    assert "top_k" not in req  # non-MiniMax default has no top_k in resolved params
    assert "thinking" not in req
    assert "metadata" not in req


def test_triager_bound_tool_choice_context_escalates_then_relaxes() -> None:
    ctx = TriagerBoundToolChoiceContext(
        bound_tools=frozenset({"log_query"}),
        bound_skills=frozenset(),
    )
    assert ctx.anthropic_tool_choice_type() == "any"
    assert ctx.openai_tool_choice() == "required"
    ctx.successful_tools_called.add("log_query")
    assert ctx.anthropic_tool_choice_type() == "auto"
    assert ctx.openai_tool_choice() == "auto"


def test_must_satisfy_tools_keeps_any_until_log_query() -> None:
    ctx = TriagerBoundToolChoiceContext(
        bound_tools=frozenset({"log_query", "read_transcript"}),
        bound_skills=frozenset(),
        must_satisfy_tools=frozenset({"log_query"}),
    )
    ctx.successful_tools_called.add("read_transcript")
    assert ctx.anthropic_tool_choice_type() == "any"
    ctx.successful_tools_called.add("log_query")
    assert ctx.anthropic_tool_choice_type() == "auto"


def test_must_satisfy_tools_keeps_any_until_search_in_file() -> None:
    """W2.2 / msg=f26e32: bound ``search_in_file`` cannot relax until it succeeds."""
    ctx = TriagerBoundToolChoiceContext(
        bound_tools=frozenset({"search_in_file", "read"}),
        bound_skills=frozenset(),
        must_satisfy_tools=frozenset({"search_in_file"}),
    )
    ctx.successful_tools_called.add("read")
    assert ctx.anthropic_tool_choice_type() == "any"
    assert ctx.openai_tool_choice() == "required"
    ctx.successful_tools_called.add("search_in_file")
    assert ctx.anthropic_tool_choice_type() == "auto"
    assert ctx.openai_tool_choice() == "auto"


def test_must_satisfy_tools_relaxes_when_bound_list_registry_succeeds() -> None:
    """Capability turns: successful bound ``list_registry`` satisfies Guard 2 without ``read``."""
    ctx = TriagerBoundToolChoiceContext(
        bound_tools=frozenset({"list_registry", "read"}),
        bound_skills=frozenset(),
        must_satisfy_tools=frozenset({"read"}),
    )
    ctx.successful_tools_called.add("list_registry")
    assert ctx.satisfied() is True
    assert ctx.anthropic_tool_choice_type() == "auto"
    assert ctx.openai_tool_choice() == "auto"


@pytest.mark.asyncio
async def test_minimax_triager_bound_first_round_uses_any_then_auto() -> None:
    transport = _CapturingAnthropic(proxy_base_url="http://test")
    ctx = TriagerBoundToolChoiceContext(
        bound_tools=frozenset({"log_query"}),
        bound_skills=frozenset(),
    )
    model = build_tier_b_function_model(
        bundle=ResolvedTierBModel(
            model_id="minimax/MiniMax-M2",
            transport=transport,
            budget=ModelBudget(model_id="minimax/MiniMax-M2", regime=BudgetRegime.PER_TOKEN),
        ),
        steer_buffer=None,
        trace=None,
        session_id="sess-1",
        turn_id="turn-1",
        provider_round_counter=[0],
        agent="tier_b",
        triager_bound_tool_choice=ctx,
    )
    await model.function(
        [ModelRequest(parts=[UserPromptPart(content="check logs")])],
        _info(with_tools=True),
    )
    assert transport.captured["tool_choice"] == {"type": "any"}

    ctx.successful_tools_called.add("log_query")
    await model.function(
        [ModelRequest(parts=[UserPromptPart(content="summarize")])],
        _info(with_tools=True),
    )
    assert transport.captured["tool_choice"] == {"type": "auto"}
