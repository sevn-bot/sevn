"""W4 MiniMaxWrapperModel — XML recovery on batch + streaming paths."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    TextPart,
    TextPartDelta,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel

from sevn.agent.adapters.minimax_wrapper_model import (
    MiniMaxHygieneContext,
    MiniMaxWrapperModel,
    wrap_minimax_native_model,
)
from sevn.agent.adapters.tier_b_model import anthropic_completion_to_model_response
from sevn.agent.providers.transport import (
    StreamFinal,
    StreamTextDelta,
    _reconstruct_anthropic_stream,
)


def _info(*, with_tools: bool = False) -> AgentInfo:
    from pydantic_ai.tools import ToolDefinition as PAToolDefinition

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


def _xml_text(tool_name: str = "read") -> str:
    return f'<invoke name="{tool_name}"><parameter name="file_path">a.py</parameter></invoke>'


def _anthropic_xml_payload(tool_name: str = "read") -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": _xml_text(tool_name)}],
        "usage": {"input_tokens": 3, "output_tokens": 5},
        "stop_reason": "tool_use",
    }


@pytest.mark.asyncio
async def test_request_recovers_xml_tool_call_parts() -> None:
    payload = _anthropic_xml_payload("read")

    async def _llm(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return anthropic_completion_to_model_response(payload)

    inner = FunctionModel(_llm, model_name="MiniMax-M2")
    wrapped = MiniMaxWrapperModel(
        inner,
        catalog_model_id="minimax/MiniMax-M2",
        hygiene=MiniMaxHygieneContext(agent="tier_b"),
    )
    response = await wrapped.request(
        [ModelRequest(parts=[UserPromptPart(content="read file")])],
        None,
        ModelRequestParameters(),
    )
    tool_names = [p.tool_name for p in response.parts if isinstance(p, ToolCallPart)]
    assert tool_names == ["read"]
    assert not any(isinstance(p, TextPart) and "<invoke" in p.content for p in response.parts)


@pytest.mark.asyncio
async def test_request_stream_recovers_xml_on_final_get() -> None:
    """Streamed path forwards live text; ``get()`` applies XML recovery (W4.2)."""
    xml = _xml_text("glob")

    async def _llm(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return anthropic_completion_to_model_response(_anthropic_xml_payload("glob"))

    async def _stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        yield xml[:12]
        yield xml[12:]

    inner = FunctionModel(_llm, stream_function=_stream, model_name="MiniMax-M2")
    wrapped = MiniMaxWrapperModel(
        inner,
        catalog_model_id="minimax/MiniMax-M2",
        hygiene=MiniMaxHygieneContext(agent="tier_b"),
    )
    text_deltas: list[str] = []
    async with wrapped.request_stream(
        [ModelRequest(parts=[UserPromptPart(content="glob")])],
        None,
        ModelRequestParameters(),
    ) as stream:
        async for event in stream:
            if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                text_deltas.append(event.delta.content_delta)
        final = stream.get()
    tool_names = [p.tool_name for p in final.parts if isinstance(p, ToolCallPart)]
    assert tool_names == ["glob"]
    assert text_deltas, "expected at least one progressive text delta"
    assert any(isinstance(p, ToolCallPart) for p in final.parts)


@pytest.mark.asyncio
async def test_wrapper_stream_proxy_yields_progressive_text() -> None:
    async def _llm(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="Hello!")])

    async def _stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        yield "Hel"
        yield "lo!"

    inner = FunctionModel(_llm, stream_function=_stream, model_name="MiniMax-M2")
    wrapped = MiniMaxWrapperModel(
        inner,
        catalog_model_id="minimax/MiniMax-M2",
        hygiene=MiniMaxHygieneContext(agent="tier_b"),
    )
    seen: list[str] = []
    async with wrapped.request_stream(
        [ModelRequest(parts=[UserPromptPart(content="hi")])],
        None,
        ModelRequestParameters(),
    ) as stream:
        async for event in stream:
            if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                seen.append(event.delta.content_delta)
        final = stream.get()
    assert seen, "expected progressive stream deltas"
    assert "".join(seen) in "Hello!"
    assert any(isinstance(p, TextPart) and p.content == "Hello!" for p in final.parts)


@pytest.mark.asyncio
async def test_reconstruct_stream_then_recovery_matches_batch() -> None:
    """Reassembled SSE + recovery matches ``anthropic_completion_to_model_response`` (W4.5)."""
    events = [
        {
            "type": "message_start",
            "message": {"model": "MiniMax-M2", "usage": {"input_tokens": 2}},
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": _xml_text("read")[:20]},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": _xml_text("read")[20:]},
        },
        {"type": "message_delta", "usage": {"output_tokens": 4}},
        {"type": "message_stop"},
    ]

    async def _events() -> AsyncIterator[dict[str, Any]]:
        for ev in events:
            yield ev

    deltas: list[str] = []
    final_payload: dict[str, Any] | None = None
    async for chunk in _reconstruct_anthropic_stream(_events()):
        if isinstance(chunk, StreamTextDelta):
            deltas.append(chunk.text)
        elif isinstance(chunk, StreamFinal):
            final_payload = chunk.response

    assert final_payload is not None
    assert "".join(deltas) == _xml_text("read")
    batch = anthropic_completion_to_model_response(_anthropic_xml_payload("read"))
    stream = anthropic_completion_to_model_response(final_payload)
    assert [type(p).__name__ for p in batch.parts] == [type(p).__name__ for p in stream.parts]
    assert [getattr(p, "tool_name", None) for p in batch.parts if isinstance(p, ToolCallPart)] == [
        "read"
    ]


def test_wrap_skips_non_minimax_catalog_ids() -> None:
    async def _noop(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="ok")])

    inner = FunctionModel(_noop, model_name="claude")
    same = wrap_minimax_native_model(
        inner,
        catalog_model_id="anthropic/claude-haiku",
        hygiene=MiniMaxHygieneContext(agent="tier_b"),
    )
    assert same is inner


def test_prepare_request_applies_minimax_hygiene_with_tools() -> None:
    async def _noop(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="ok")])

    inner = FunctionModel(_noop, model_name="MiniMax-M2")
    wrapped = MiniMaxWrapperModel(
        inner,
        catalog_model_id="minimax/MiniMax-M2",
        hygiene=MiniMaxHygieneContext(
            agent="tier_b",
            session_id="sess-1",
            turn_id="turn-1",
            user_id="user-9",
            channel="telegram",
            workspace_id="ws-1",
            executor_tier="B",
        ),
    )
    settings, _params = wrapped.prepare_request(
        {"top_k": 40, "temperature": 1.0},
        ModelRequestParameters(
            function_tools=_info(with_tools=True).function_tools,
        ),
    )
    assert settings is not None
    assert "top_k" not in settings
    assert settings.get("tool_choice") == {"type": "auto"}


def test_minimax_wrapper_triager_bound_unsatisfied_uses_any() -> None:
    from sevn.agent.adapters.tier_b_model import TriagerBoundToolChoiceContext

    async def _noop(messages, info):
        return ModelResponse(parts=[TextPart(content="ok")])

    inner = FunctionModel(_noop, model_name="MiniMax-M2")
    wrapped = MiniMaxWrapperModel(
        inner,
        catalog_model_id="minimax/MiniMax-M2",
        hygiene=MiniMaxHygieneContext(
            agent="tier_b",
            triager_bound_tool_choice=TriagerBoundToolChoiceContext(
                bound_tools=frozenset({"log_query"}),
            ),
        ),
    )
    settings, _params = wrapped.prepare_request(
        None,
        ModelRequestParameters(
            function_tools=_info(with_tools=True).function_tools,
        ),
    )
    assert settings is not None
    assert settings.get("tool_choice") == {"type": "any"}


@pytest.mark.asyncio
async def test_recovered_streamed_response_get_applies_recovery() -> None:
    from pydantic_ai.models.wrapper import CompletedStreamedResponse

    from sevn.agent.adapters.minimax_wrapper_model import _RecoveredStreamedResponse

    batch = anthropic_completion_to_model_response(_anthropic_xml_payload("read"))
    inner = CompletedStreamedResponse(ModelRequestParameters(), batch)
    recovered = _RecoveredStreamedResponse(inner)
    final = recovered.get()
    assert [p.tool_name for p in final.parts if isinstance(p, ToolCallPart)] == ["read"]
