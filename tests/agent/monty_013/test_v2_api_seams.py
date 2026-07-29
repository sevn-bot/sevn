"""W1.6 — pydantic-ai v2 API seam contracts (D10, D11, D8)."""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic_ai.usage import RunUsage

from sevn.agent.adapters.tier_b_capabilities import build_web_thinking_extra_capabilities
from sevn.config.workspace_config import WorkspaceConfig
from sevn.tools.base import ToolExecutor


def test_run_usage_exposes_v2_token_fields_only() -> None:
    usage = RunUsage(input_tokens=3, output_tokens=7)
    assert usage.input_tokens == 3
    assert usage.output_tokens == 7
    assert not hasattr(usage, "request_tokens")
    assert not hasattr(usage, "response_tokens")


@pytest.mark.asyncio
async def test_streaming_uses_property_accessors_not_callables() -> None:
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel

    async def model_fn(messages: list[object], info: MagicMock) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="hi")])

    async def stream_fn(messages: list[object], info: MagicMock):
        yield "hi"

    agent = Agent(FunctionModel(model_fn, stream_function=stream_fn))
    async with agent.run_stream("ping") as stream:
        assert not callable(getattr(stream, "usage", None))
        _ = stream.usage
        assert await stream.get_output() == "hi"


def test_web_search_native_with_local_fallback_constructor() -> None:
    from pydantic_ai.capabilities import WebSearch

    async def local_serp(**kwargs: object) -> str:
        return "ok"

    cap = WebSearch(native=True, local=local_serp)
    assert cap.native is not None
    assert cap.local is not None
    assert getattr(cap.local, "function", cap.local) is local_serp


def test_web_fetch_native_with_local_fallback_constructor() -> None:
    from pydantic_ai.capabilities import WebFetch

    async def local_fetch(**kwargs: object) -> str:
        return "ok"

    cap = WebFetch(native=True, local=local_fetch)
    assert cap.native is not None
    assert cap.local is not None
    assert getattr(cap.local, "function", cap.local) is local_fetch


def test_build_web_thinking_extra_never_uses_exa_research() -> None:
    ws = WorkspaceConfig.minimal()
    exe = ToolExecutor()
    caps, _ = build_web_thinking_extra_capabilities(
        workspace=ws,
        model_id="anthropic/claude-sonnet-4-20250514",
        tool_executor=exe,
        triage_tools=("serp", "get_page_content"),
        codemode_enabled=False,
    )
    for cap in caps:
        mod = cap.__class__.__module__
        assert "exa" not in mod.lower()


def test_model_profile_accessed_as_typed_dict() -> None:
    from sevn.agent.adapters.tier_b_model import read_model_profile_field

    profile: dict[str, Any] = {"supports_tools": True, "max_tokens": 8192}
    assert read_model_profile_field(profile, "supports_tools", default=False) is True
    assert read_model_profile_field(profile, "missing", default="fallback") == "fallback"


def test_bare_model_name_rejected_without_provider_prefix() -> None:
    from sevn.agent.adapters.tier_b_model import normalize_tier_b_model_name

    with pytest.raises(ValueError, match="provider"):
        normalize_tier_b_model_name("gpt-5")
    assert normalize_tier_b_model_name("openai-chat:gpt-5") == "openai-chat:gpt-5"


def test_codemode_constructor_signature_matches_harness_wheel() -> None:
    from sevn.agent.adapters.tier_b_async_codemode import SevnAsyncCodeMode

    params = list(inspect.signature(SevnAsyncCodeMode).parameters)
    assert "tools" in params
    assert "max_retries" in params
    assert "dynamic_catalog" in params


def test_instrumentation_disables_aggregated_usage_attributes() -> None:
    from sevn.tracing.otel_pipeline import instrumentation_capability

    cap = instrumentation_capability()
    settings = getattr(cap, "settings", None) or getattr(cap, "_settings", None)
    assert settings is not None
    assert getattr(settings, "use_aggregated_usage_attribute_names", True) is False
