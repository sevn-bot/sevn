"""W5: MiniMax empty ``content`` + ``end_turn`` soft-retry nudge at transport layer."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo

from sevn.agent.adapters.tier_b_model import (
    _EMPTY_CONTENT_NUDGE_TEMPERATURE,
    _EMPTY_CONTENT_NUDGE_USER_TEXT,
    build_tier_b_function_model,
    is_anthropic_empty_end_turn,
)
from sevn.agent.executors.b_types import ResolvedTierBModel
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import AnthropicMessagesTransport
from sevn.agent.triager import run as triager_run
from sevn.agent.triager.context import (
    ApprovedUserTurn,
    RegistrySnapshot,
    SessionView,
    TriagePromptContext,
)
from sevn.agent.triager.models import ComplexityTier, Intent
from sevn.agent.triager.run import _is_empty_output_retry_error
from sevn.config.workspace_config import parse_workspace_config


def _info() -> AgentInfo:
    return AgentInfo(
        function_tools=[],
        allow_text_output=True,
        output_tools=[],
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
        instructions=None,
    )


def test_is_empty_output_retry_error() -> None:
    assert _is_empty_output_retry_error(RuntimeError("Exceeded maximum output retries (3)"))
    assert not _is_empty_output_retry_error(ValueError("bad"))


def test_is_anthropic_empty_end_turn_detects_blank_end_turn() -> None:
    assert is_anthropic_empty_end_turn({"content": [], "stop_reason": "end_turn"})
    assert not is_anthropic_empty_end_turn(
        {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"}
    )


class _SeqAnthropic(AnthropicMessagesTransport):
    """Return empty ``end_turn`` once, then text."""

    def __init__(self) -> None:
        super().__init__(proxy_base_url="http://test")
        self.calls: list[dict[str, object]] = []

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        self.calls.append(dict(request))
        if len(self.calls) == 1:
            return {
                "content": [],
                "stop_reason": "end_turn",
                "model": "minimax/MiniMax-M2",
                "usage": {"input_tokens": 1, "output_tokens": 0},
            }
        return {
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }


@pytest.mark.asyncio
async def test_empty_content_nudges_once_then_succeeds() -> None:
    transport = _SeqAnthropic()
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
        agent="triager",
    )
    response = await model.function(
        [ModelRequest(parts=[UserPromptPart(content="hi")])],
        _info(),
    )
    assert any(p.content == "ok" for p in response.parts if hasattr(p, "content"))
    assert len(transport.calls) == 2
    assert _EMPTY_CONTENT_NUDGE_USER_TEXT in json.dumps(transport.calls[1])
    assert transport.calls[1]["temperature"] == pytest.approx(_EMPTY_CONTENT_NUDGE_TEMPERATURE)


class _AlwaysEmptyAnthropic(AnthropicMessagesTransport):
    def __init__(self) -> None:
        super().__init__(proxy_base_url="http://test")
        self.calls = 0

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        self.calls += 1
        return {
            "content": [],
            "stop_reason": "end_turn",
            "model": "minimax/MiniMax-M2",
            "usage": {"input_tokens": 1, "output_tokens": 0},
        }


@pytest.mark.asyncio
async def test_repeated_empty_content_caps_provider_calls() -> None:
    """Empty → nudge → still empty should not loop; at most two completes per round."""
    transport = _AlwaysEmptyAnthropic()
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
        agent="triager",
    )
    response = await model.function(
        [ModelRequest(parts=[UserPromptPart(content="hi")])],
        _info(),
    )
    assert transport.calls == 2
    assert all(
        not getattr(p, "content", "").strip() for p in response.parts if hasattr(p, "content")
    )


_VALID_TRIAGE_JSON = json.dumps(
    {
        "intent": Intent.NEW_REQUEST.value,
        "complexity": ComplexityTier.B.value,
        "first_message": "On it.",
        "tools": [],
        "skills": [],
        "mcp_servers_required": [],
        "confidence": 0.5,
        "requires_vision": False,
        "requires_document": False,
        "disregard": False,
    }
)


@pytest.mark.asyncio
async def test_triager_empty_then_valid_json_via_nudge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Triager path: one empty Anthropic response, nudge returns valid TriageResult JSON."""
    calls = {"n": 0}

    async def fake_post(**kwargs: object) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "content": [],
                "stop_reason": "end_turn",
                "model": "minimax/MiniMax-M3",
                "usage": {"input_tokens": 1, "output_tokens": 0},
            }
        return {
            "content": [{"type": "text", "text": _VALID_TRIAGE_JSON}],
            "stop_reason": "end_turn",
            "model": "minimax/MiniMax-M3",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.setenv("SEVN_TRIAGER_STUB", "0")
    monkeypatch.setenv("SEVN_PROXY_URL", "http://triager-empty.test")
    monkeypatch.setattr(
        "sevn.agent.providers.transport.transport_http.post_llm_json",
        fake_post,
    )
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "providers": {
                "tier_default": {"triager": "minimax/MiniMax-M3"},
                "models": {"minimax/MiniMax-M3": {"transport": "anthropic"}},
            },
            "permissions": {"scope_narrowing": {"enabled": False}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    out = await triager_run.triage_turn(
        workspace=ws,
        session=SessionView(session_id="s-empty-nudge"),
        incoming=ApprovedUserTurn(text="route"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(current_message="route"),
    )
    assert calls["n"] == 2
    assert out.complexity == ComplexityTier.B
    assert out.first_message == "On it."


@pytest.mark.asyncio
async def test_triager_repeated_empty_falls_back_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated empty Anthropic bodies → synthetic fallback without a long retry storm."""

    async def always_empty(**kwargs: object) -> dict[str, Any]:
        return {
            "content": [],
            "stop_reason": "end_turn",
            "model": "minimax/MiniMax-M3",
            "usage": {"input_tokens": 1, "output_tokens": 0},
        }

    monkeypatch.setenv("SEVN_TRIAGER_STUB", "0")
    monkeypatch.setenv("SEVN_PROXY_URL", "http://triager-empty.test")
    monkeypatch.setattr(
        "sevn.agent.providers.transport.transport_http.post_llm_json",
        always_empty,
    )
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "providers": {
                "tier_default": {"triager": "minimax/MiniMax-M3"},
                "models": {"minimax/MiniMax-M3": {"transport": "anthropic"}},
            },
            "permissions": {"scope_narrowing": {"enabled": False}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    out = await triager_run.triage_turn(
        workspace=ws,
        session=SessionView(session_id="s-empty-fallback"),
        incoming=ApprovedUserTurn(text="route"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(current_message="route"),
    )
    assert out.complexity == ComplexityTier.B
    assert out.confidence == 0.55
    assert out.first_message.strip()
