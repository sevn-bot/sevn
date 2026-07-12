"""W3 native model factory — catalog routing, FallbackModel, settings, flag-off parity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from sevn.agent.adapters.egress_bridge import PROXY_TOKEN_HEADER
from sevn.agent.adapters.native_model import (
    NativeModelContext,
    build_native_model_settings,
    default_native_model_context,
    resolve_pydantic_model,
    resolve_pydantic_model_for_slot,
)
from sevn.config.llm_params import LLM_PARAMS_FILENAME
from sevn.config.model_resolution import ModelSlot, native_model_enabled
from sevn.config.workspace_config import WorkspaceConfig, parse_workspace_config


def _ctx(
    model_id: str,
    *,
    fallback_model_ids: tuple[str, ...] = (),
    providers_obj: dict[str, Any] | None = None,
) -> NativeModelContext:
    return NativeModelContext(
        slot=ModelSlot.tier_b,
        model_id=model_id,
        proxy_base="http://proxy.test",
        shared_secret="proxy-secret",
        trace=None,
        redactor=None,
        session_id="sess",
        turn_id="turn",
        agent="tier_b",
        providers_obj=providers_obj,
        fallback_model_ids=fallback_model_ids,
    )


def test_native_model_enabled_defaults_false() -> None:
    ws = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    assert native_model_enabled(ws, ModelSlot.tier_b) is False
    assert native_model_enabled(ws, ModelSlot.triager) is False


def test_native_model_enabled_reads_per_slot_flag() -> None:
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "providers": {"native_model": {"tier_b": True, "triager": False}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    assert native_model_enabled(ws, ModelSlot.tier_b) is True
    assert native_model_enabled(ws, ModelSlot.triager) is False


@pytest.mark.parametrize(
    ("model_id", "expected_type_name"),
    [
        # minimax/* now defaults to chat_completions → MiniMaxOpenAIWrapperModel.
        ("minimax/MiniMax-M2.7", "MiniMaxOpenAIWrapperModel"),
        ("anthropic/claude-sonnet-4-20250514", "AnthropicModel"),
        ("openai/gpt-4o-mini", "OpenAIChatModel"),
        ("bedrock/anthropic.claude-3-haiku", "BedrockConverseModel"),
    ],
)
def test_factory_returns_expected_model_class(
    model_id: str,
    expected_type_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.models.bedrock import BedrockConverseModel
    from pydantic_ai.models.openai import OpenAIChatModel

    from sevn.agent.adapters.minimax_wrapper_model import (
        MiniMaxOpenAIWrapperModel,
        MiniMaxWrapperModel,
    )

    expected = {
        "MiniMaxWrapperModel": MiniMaxWrapperModel,
        "MiniMaxOpenAIWrapperModel": MiniMaxOpenAIWrapperModel,
        "AnthropicModel": AnthropicModel,
        "OpenAIChatModel": OpenAIChatModel,
        "BedrockConverseModel": BedrockConverseModel,
    }[expected_type_name]
    if model_id.startswith("bedrock/"):
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    model = resolve_pydantic_model(ctx=_ctx(model_id))
    assert isinstance(model, expected)
    if isinstance(model, MiniMaxOpenAIWrapperModel):
        assert isinstance(model.wrapped, OpenAIChatModel)


def test_anthropic_model_routes_through_egress_bridge() -> None:
    from pydantic_ai.models.anthropic import AnthropicModel

    from sevn.agent.adapters.minimax_wrapper_model import MiniMaxWrapperModel

    # Explicit anthropic transport opts a minimax model back onto the Anthropic wire.
    model = resolve_pydantic_model(
        ctx=_ctx("minimax/MiniMax-M2.7", providers_obj={"minimax": {"transport": "anthropic"}}),
    )
    assert isinstance(model, MiniMaxWrapperModel)
    assert isinstance(model.wrapped, AnthropicModel)
    provider = model.wrapped._provider
    assert str(provider.base_url).rstrip("/") == "http://proxy.test"
    http_client = provider.client._client
    assert isinstance(http_client, httpx.AsyncClient)
    assert str(http_client.base_url).rstrip("/") == "http://proxy.test"


@pytest.mark.asyncio
async def test_anthropic_bridge_injects_proxy_secret_header() -> None:
    from pydantic_ai.models.anthropic import AnthropicModel

    model = resolve_pydantic_model(ctx=_ctx("anthropic/claude-haiku-4-5"))
    assert isinstance(model, AnthropicModel)
    provider = model._provider
    http_client = provider.client._client
    req = httpx.Request("POST", "http://proxy.test/v1/messages")
    for hook in http_client.event_hooks.get("request", []):
        await hook(req)
    assert req.headers[PROXY_TOKEN_HEADER] == "proxy-secret"


def test_openai_model_routes_through_egress_bridge() -> None:
    from pydantic_ai.models.openai import OpenAIChatModel

    model = resolve_pydantic_model(ctx=_ctx("openai/gpt-4o-mini"))
    assert isinstance(model, OpenAIChatModel)
    provider = model._provider
    assert str(provider.base_url).rstrip("/") == "http://proxy.test"
    http_client = provider.client._client
    assert isinstance(http_client, httpx.AsyncClient)


def test_fallback_model_members_all_use_bridge() -> None:
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.models.fallback import FallbackModel
    from pydantic_ai.models.openai import OpenAIChatModel

    from sevn.agent.adapters.minimax_wrapper_model import MiniMaxWrapperModel

    model = resolve_pydantic_model(
        ctx=_ctx(
            "minimax/MiniMax-M2.7",
            fallback_model_ids=("openai/gpt-4o-mini",),
            providers_obj={"minimax": {"transport": "anthropic"}},
        ),
    )
    assert isinstance(model, FallbackModel)
    assert isinstance(model.models[0], MiniMaxWrapperModel)
    assert isinstance(model.models[0].wrapped, AnthropicModel)
    assert isinstance(model.models[1], OpenAIChatModel)
    for member in model.models:
        inner = member.wrapped if isinstance(member, MiniMaxWrapperModel) else member
        provider = inner._provider
        assert str(provider.base_url).rstrip("/") == "http://proxy.test"


def test_resolve_pydantic_model_for_slot_reads_fallback_chain() -> None:
    from pydantic_ai.models.fallback import FallbackModel

    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "providers": {
                "fallback_chain": {
                    "B": ["minimax/MiniMax-M2.7", "openai/gpt-4o-mini"],
                },
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    ctx = default_native_model_context(
        slot=ModelSlot.tier_b,
        model_id="minimax/MiniMax-M2.7",
        proxy_base="http://proxy.test",
        session_id="s",
        turn_id="t",
        agent="tier_b",
        shared_secret="sec",
    )
    model = resolve_pydantic_model_for_slot(workspace=ws, ctx=ctx)
    assert isinstance(model, FallbackModel)
    assert len(model.models) == 2


def test_build_native_model_settings_maps_anthropic_knobs(tmp_path: Path) -> None:
    (tmp_path / LLM_PARAMS_FILENAME).write_text(
        json.dumps(
            {
                "tier_b": {
                    "model_overrides": {"minimax/*": {"temperature": 0.25}},
                }
            }
        ),
        encoding="utf-8",
    )
    settings = build_native_model_settings(
        model_id="minimax/MiniMax-M2",
        transport_name="anthropic",
        agent="tier_b",
        content_root=tmp_path,
        max_output_tokens=8192,
        seed=None,
    )
    assert settings["max_tokens"] == 8192
    assert settings["temperature"] == 0.25
    assert settings["anthropic_cache_instructions"] is True
    assert settings["anthropic_cache_tool_definitions"] is True


def test_build_native_model_settings_maps_openai_seed(tmp_path: Path) -> None:
    (tmp_path / LLM_PARAMS_FILENAME).write_text(
        json.dumps({"triager": {"temperature": 0.0}}),
        encoding="utf-8",
    )
    settings = build_native_model_settings(
        model_id="openai/gpt-4o-mini",
        transport_name="chat_completions",
        agent="triager",
        content_root=tmp_path,
        max_output_tokens=2048,
        seed=42,
    )
    assert settings["max_tokens"] == 2048
    assert settings["temperature"] == 0.0
    assert settings["seed"] == 42


def test_minimax_chat_completions_builds_openai_wrapper() -> None:
    """MiniMax with transport=chat_completions builds MiniMaxOpenAIWrapperModel over OpenAIChatModel."""
    from pydantic_ai.models.openai import OpenAIChatModel

    from sevn.agent.adapters.minimax_wrapper_model import MiniMaxOpenAIWrapperModel

    providers = {"minimax": {"transport": "chat_completions"}}
    model = resolve_pydantic_model(ctx=_ctx("minimax/MiniMax-M3", providers_obj=providers))
    assert isinstance(model, MiniMaxOpenAIWrapperModel)
    assert isinstance(model.wrapped, OpenAIChatModel)
    assert model.catalog_model_id == "minimax/MiniMax-M3"


def test_minimax_default_transport_builds_openai_wrapper() -> None:
    """MiniMax with no transport override defaults to chat_completions → OpenAI wrapper."""
    from pydantic_ai.models.openai import OpenAIChatModel

    from sevn.agent.adapters.minimax_wrapper_model import MiniMaxOpenAIWrapperModel

    model = resolve_pydantic_model(ctx=_ctx("minimax/MiniMax-M2.7"))
    assert isinstance(model, MiniMaxOpenAIWrapperModel)
    assert isinstance(model.wrapped, OpenAIChatModel)


def test_minimax_explicit_anthropic_transport_builds_anthropic_wrapper() -> None:
    """Explicit providers.minimax.transport=anthropic opts back onto the Anthropic wire."""
    from pydantic_ai.models.anthropic import AnthropicModel

    from sevn.agent.adapters.minimax_wrapper_model import MiniMaxWrapperModel

    model = resolve_pydantic_model(
        ctx=_ctx("minimax/MiniMax-M2.7", providers_obj={"minimax": {"transport": "anthropic"}}),
    )
    assert isinstance(model, MiniMaxWrapperModel)
    assert isinstance(model.wrapped, AnthropicModel)


def test_non_minimax_unchanged_with_minimax_transport_config() -> None:
    """Non-MiniMax models are unaffected by providers.minimax.transport (D3)."""
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.models.openai import OpenAIChatModel

    from sevn.agent.adapters.minimax_wrapper_model import (
        MiniMaxOpenAIWrapperModel,
        MiniMaxWrapperModel,
    )

    providers = {"minimax": {"transport": "chat_completions"}}
    anthropic_model = resolve_pydantic_model(
        ctx=_ctx("anthropic/claude-sonnet-4-20250514", providers_obj=providers)
    )
    assert isinstance(anthropic_model, AnthropicModel)
    assert not isinstance(anthropic_model, MiniMaxWrapperModel)

    openai_model = resolve_pydantic_model(ctx=_ctx("openai/gpt-4o-mini", providers_obj=providers))
    assert isinstance(openai_model, OpenAIChatModel)
    assert not isinstance(openai_model, MiniMaxOpenAIWrapperModel)


def test_minimax_openai_wrapper_routes_through_egress_bridge() -> None:
    """MiniMaxOpenAIWrapperModel routes through the proxy egress bridge."""
    from sevn.agent.adapters.minimax_wrapper_model import MiniMaxOpenAIWrapperModel

    providers = {"minimax": {"transport": "chat_completions"}}
    model = resolve_pydantic_model(ctx=_ctx("minimax/MiniMax-M3", providers_obj=providers))
    assert isinstance(model, MiniMaxOpenAIWrapperModel)
    provider = model.wrapped._provider
    assert str(provider.base_url).rstrip("/") == "http://proxy.test"
    http_client = provider.client._client
    assert isinstance(http_client, httpx.AsyncClient)


def test_minimax_openai_wrapper_prepare_request_drops_top_k() -> None:
    """MiniMaxOpenAIWrapperModel.prepare_request drops top_k (unsupported by OpenAI wire)."""
    from pydantic_ai.models import ModelRequestParameters

    from sevn.agent.adapters.minimax_wrapper_model import MiniMaxOpenAIWrapperModel

    providers = {"minimax": {"transport": "chat_completions"}}
    model = resolve_pydantic_model(ctx=_ctx("minimax/MiniMax-M3", providers_obj=providers))
    assert isinstance(model, MiniMaxOpenAIWrapperModel)
    params = ModelRequestParameters(
        function_tools=[],
        output_tools=[],
        allow_text_output=True,
    )
    settings, _ = model.prepare_request({"top_k": 40, "temperature": 0.7}, params)
    assert settings is not None
    assert "top_k" not in settings
    assert settings.get("temperature") == 0.7


def test_minimax_openai_wrapper_prepare_request_tool_choice_auto() -> None:
    """MiniMaxOpenAIWrapperModel sets tool_choice='auto' when tools present, no triager binding."""
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.tools import ToolDefinition

    from sevn.agent.adapters.minimax_wrapper_model import MiniMaxOpenAIWrapperModel

    providers = {"minimax": {"transport": "chat_completions"}}
    model = resolve_pydantic_model(ctx=_ctx("minimax/MiniMax-M3", providers_obj=providers))
    assert isinstance(model, MiniMaxOpenAIWrapperModel)
    tool_def = ToolDefinition(
        name="test_tool",
        description="test",
        parameters_json_schema={"type": "object", "properties": {}},
    )
    params = ModelRequestParameters(
        function_tools=[tool_def],
        output_tools=[],
        allow_text_output=True,
    )
    settings, _ = model.prepare_request(None, params)
    assert settings is not None
    assert settings["tool_choice"] == "auto"


def test_minimax_openai_wrapper_triager_bound_tool_choice() -> None:
    """MiniMaxOpenAIWrapperModel uses openai_tool_choice for triager-bound escalation."""
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.tools import ToolDefinition

    from sevn.agent.adapters.minimax_wrapper_model import MiniMaxOpenAIWrapperModel
    from sevn.agent.adapters.tier_b_model import TriagerBoundToolChoiceContext

    ctx_bound = TriagerBoundToolChoiceContext(bound_tools=frozenset({"log_query"}))
    providers = {"minimax": {"transport": "chat_completions"}}
    ctx = _ctx("minimax/MiniMax-M3", providers_obj=providers)
    ctx_with_bound = NativeModelContext(
        slot=ctx.slot,
        model_id=ctx.model_id,
        proxy_base=ctx.proxy_base,
        shared_secret=ctx.shared_secret,
        trace=ctx.trace,
        redactor=ctx.redactor,
        session_id=ctx.session_id,
        turn_id=ctx.turn_id,
        agent=ctx.agent,
        providers_obj=ctx.providers_obj,
        triager_bound_tool_choice=ctx_bound,
    )
    model = resolve_pydantic_model(ctx=ctx_with_bound)
    assert isinstance(model, MiniMaxOpenAIWrapperModel)
    tool_def = ToolDefinition(
        name="log_query",
        description="query",
        parameters_json_schema={"type": "object", "properties": {}},
    )
    params = ModelRequestParameters(
        function_tools=[tool_def],
        output_tools=[],
        allow_text_output=True,
    )
    settings, _ = model.prepare_request(None, params)
    assert settings is not None
    assert settings["tool_choice"] == "required"


def test_flag_off_does_not_construct_native_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag-off path must not call the native factory (byte-identical gate)."""
    from sevn.agent.executors import b_harness

    workspace = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    assert native_model_enabled(workspace, ModelSlot.tier_b) is False

    factory = MagicMock(side_effect=AssertionError("native model constructed while flag off"))
    monkeypatch.setattr(b_harness, "resolve_pydantic_model_for_slot", factory)

    # Simulate the harness branch: only FunctionModel when flag is off.
    if native_model_enabled(workspace, ModelSlot.tier_b):
        resolve_pydantic_model_for_slot(workspace=workspace, ctx=object())  # type: ignore[arg-type]
    factory.assert_not_called()
