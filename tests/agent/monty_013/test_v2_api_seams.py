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


@pytest.mark.xfail(reason="green after W2: RunUsage v2 token field names", strict=False)
def test_run_usage_exposes_v2_token_fields_only() -> None:
    usage = RunUsage(input_tokens=3, output_tokens=7)
    assert usage.input_tokens == 3
    assert usage.output_tokens == 7
    assert not hasattr(usage, "request_tokens")
    assert not hasattr(usage, "response_tokens")


@pytest.mark.xfail(reason="green after W2: streaming result property accessors", strict=False)
@pytest.mark.asyncio
async def test_streaming_uses_property_accessors_not_callables() -> None:
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel

    async def model_fn(messages: list[object], info: MagicMock) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="hi")])

    agent = Agent(FunctionModel(model_fn))
    async with agent.run_stream("ping") as stream:
        assert not callable(getattr(stream, "usage", None))
        _ = stream.usage
        response = await stream.get_response()
        assert response.output == "hi"


@pytest.mark.xfail(reason="green after W3: WebSearch native+local constructor (D8)", strict=False)
def test_web_search_native_with_local_fallback_constructor() -> None:
    from pydantic_ai.capabilities import WebSearch

    local_tool = MagicMock()
    cap = WebSearch(native=True, local=local_tool)
    assert cap.native is True
    assert cap.local is local_tool


@pytest.mark.xfail(reason="green after W3: WebFetch native+local constructor (D8)", strict=False)
def test_web_fetch_native_with_local_fallback_constructor() -> None:
    from pydantic_ai.capabilities import WebFetch

    local_tool = MagicMock()
    cap = WebFetch(native=True, local=local_tool)
    assert cap.native is True
    assert cap.local is local_tool


@pytest.mark.xfail(reason="green after W3: sevn keeps registry fallback not Exa (D8)", strict=False)
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


@pytest.mark.xfail(reason="green after W3: ModelProfile TypedDict .get() access", strict=False)
def test_model_profile_accessed_as_typed_dict() -> None:
    from sevn.agent.adapters.tier_b_model import read_model_profile_field

    profile: dict[str, Any] = {"supports_tools": True, "max_tokens": 8192}
    assert read_model_profile_field(profile, "supports_tools", default=False) is True
    assert read_model_profile_field(profile, "missing", default="fallback") == "fallback"


@pytest.mark.xfail(reason="green after W3: provider-prefixed model names required", strict=False)
def test_bare_model_name_rejected_without_provider_prefix() -> None:
    from sevn.agent.adapters.tier_b_model import normalize_tier_b_model_name

    with pytest.raises(ValueError, match="provider"):
        normalize_tier_b_model_name("gpt-5")
    assert normalize_tier_b_model_name("openai-chat:gpt-5") == "openai-chat:gpt-5"


@pytest.mark.xfail(reason="green after W3: CodeMode wheel signature pinned (D10)", strict=False)
def test_codemode_constructor_signature_matches_harness_wheel() -> None:
    from pydantic_ai_harness import CodeMode

    params = list(inspect.signature(CodeMode).parameters)
    assert "tools" in params
    assert "max_retries" in params
    assert "dynamic_catalog" in params
    assert "resource_limits" in params


@pytest.mark.xfail(reason="green after W3: OTel holds v4 usage attribute shape (D11)", strict=False)
def test_instrumentation_disables_aggregated_usage_attributes() -> None:
    from sevn.tracing.otel_pipeline import instrumentation_capability

    cap = instrumentation_capability()
    settings = getattr(cap, "settings", None) or getattr(cap, "_settings", None)
    assert settings is not None
    assert getattr(settings, "use_aggregated_usage_attribute_names", True) is False
