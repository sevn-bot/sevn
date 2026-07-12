"""W7.4/W7.5/W10: sampling params reach the function-model request per transport.

Drives ``build_tier_b_function_model`` with a request-capturing transport and
asserts:
- MiniMax catalog ids on the anthropic wire carry temperature 1.0 / top_p 0.95
  with NO ``top_k`` (W10 / D2 — MiniMax ignores top_k on anthropic wire).
- The triager case reads sampling from the workspace file (no caller override) and
  threads deterministic seed fallback into the chat_completions request, with NO ``top_k``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo

from sevn.agent.adapters.tier_b_model import build_tier_b_function_model
from sevn.agent.executors.b_types import ResolvedTierBModel
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import (
    AnthropicMessagesTransport,
    ChatCompletionsTransport,
)
from sevn.config.llm_params import LLM_PARAMS_FILENAME


def _info() -> AgentInfo:
    return AgentInfo(
        function_tools=[],
        allow_text_output=True,
        output_tools=[],
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
        instructions=None,
    )


class _CapturingChat(ChatCompletionsTransport):
    captured: dict[str, object]

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        self.captured = dict(request)
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }


class _CapturingAnthropic(AnthropicMessagesTransport):
    captured: dict[str, object]

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        self.captured = dict(request)
        return {
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }


@pytest.mark.asyncio
async def test_minimax_anthropic_request_carries_d4_defaults() -> None:
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
    )
    await model.function([ModelRequest(parts=[UserPromptPart(content="hi")])], _info())
    req = transport.captured
    assert req["temperature"] == pytest.approx(1.0)
    assert req["top_p"] == pytest.approx(0.95)
    assert "top_k" not in req  # W10: dropped for MiniMax on anthropic wire
    assert "seed" not in req  # anthropic wire drops seed


@pytest.mark.asyncio
async def test_triager_chat_request_carries_workspace_temperature_and_seed(
    tmp_path: Path,
) -> None:
    (tmp_path / LLM_PARAMS_FILENAME).write_text(
        json.dumps({"triager": {"temperature": 0.11}}),
        encoding="utf-8",
    )
    transport = _CapturingChat(proxy_base_url="http://test")
    model = build_tier_b_function_model(
        bundle=ResolvedTierBModel(
            model_id="openai:gpt-4o-mini",
            transport=transport,
            budget=ModelBudget(model_id="openai:gpt-4o-mini", regime=BudgetRegime.PER_TOKEN),
        ),
        steer_buffer=None,
        trace=None,
        session_id="triager",
        turn_id="triager",
        provider_round_counter=[0],
        agent="triager",
        content_root=tmp_path,
        seed=12345,
    )
    await model.function([ModelRequest(parts=[UserPromptPart(content="hi")])], _info())
    req = transport.captured
    assert req["temperature"] == pytest.approx(0.11)
    assert req["seed"] == 12345
    assert "top_k" not in req  # chat_completions drops top_k


@pytest.mark.asyncio
async def test_triager_minimax_workspace_override_not_bypassed(tmp_path: Path) -> None:
    (tmp_path / LLM_PARAMS_FILENAME).write_text(
        json.dumps(
            {
                "triager": {
                    "temperature": 0.0,
                    "model_overrides": {
                        "minimax/*": {"temperature": 1.0, "top_p": 0.95, "top_k": 40}
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    transport = _CapturingAnthropic(proxy_base_url="http://test")
    model = build_tier_b_function_model(
        bundle=ResolvedTierBModel(
            model_id="minimax/MiniMax-M3",
            transport=transport,
            budget=ModelBudget(model_id="minimax/MiniMax-M3", regime=BudgetRegime.PER_TOKEN),
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
    assert req["temperature"] == pytest.approx(1.0)
    assert req["top_p"] == pytest.approx(0.95)
    assert "top_k" not in req


@pytest.mark.asyncio
async def test_workspace_override_reaches_anthropic_request(tmp_path: Path) -> None:
    (tmp_path / LLM_PARAMS_FILENAME).write_text(
        json.dumps(
            {
                "tier_b": {
                    "temperature": 0.0,
                    "model_overrides": {
                        "minimax/*": {"temperature": 0.66, "top_p": 0.5, "top_k": 7}
                    },
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
    assert req["temperature"] == pytest.approx(0.66)
    assert req["top_p"] == pytest.approx(0.5)
    assert "top_k" not in req  # W10: workspace top_k override still dropped for MiniMax
