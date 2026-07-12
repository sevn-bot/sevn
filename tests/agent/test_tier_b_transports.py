"""Tier-B multi-transport serializer tests (`specs/14-executor-tier-b.md` Wave P)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    UserPromptPart,
)

from sevn.agent.adapters.tier_b_model import (
    _display_text_from_model_response,
    anthropic_completion_to_model_response,
    bedrock_converse_to_model_response,
    openai_completion_to_model_response,
    pydantic_messages_to_anthropic_messages,
    pydantic_messages_to_bedrock_converse,
)
from sevn.agent.providers.transport import (
    AnthropicMessagesTransport,
    AnthropicTransport,
    BedrockTransport,
    ChatCompletionsTransport,
    ResponsesApiTransport,
    StreamFinal,
    StreamTextDelta,
)

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "llm"


def _load(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def test_pydantic_messages_to_anthropic_user_string() -> None:
    msgs = [ModelRequest(parts=[UserPromptPart(content="hello triager")])]
    out = pydantic_messages_to_anthropic_messages(msgs)
    assert out == [{"role": "user", "content": "hello triager"}]


def test_anthropic_completion_fixture_text_part() -> None:
    data = _load("anthropic_messages_response_text.json")
    resp = anthropic_completion_to_model_response(data)
    assert any(p.content == "Routing to tier B." for p in resp.parts if hasattr(p, "content"))


def test_anthropic_thinking_tool_use_round_trip_batch() -> None:
    """Ingest preserves block order; egress reproduces provider ``content`` block-for-block."""
    api_content = [
        {"type": "thinking", "thinking": "plan step", "signature": "sig-abc"},
        {
            "type": "tool_use",
            "id": "toolu_01",
            "name": "read",
            "input": {"file_path": "src/a.py"},
        },
    ]
    data = {"content": api_content, "usage": {"input_tokens": 4, "output_tokens": 6}}
    resp = anthropic_completion_to_model_response(data)
    assert [type(p).__name__ for p in resp.parts] == ["ThinkingPart", "ToolCallPart"]
    think = resp.parts[0]
    assert isinstance(think, ThinkingPart)
    assert think.content == "plan step"
    assert think.signature == "sig-abc"
    assert think.provider_name == "anthropic"
    tool = resp.parts[1]
    assert isinstance(tool, ToolCallPart)
    assert tool.tool_name == "read"
    assert tool.tool_call_id == "toolu_01"
    assert resp.metadata is not None
    assert resp.metadata["anthropic_content"] == api_content

    out = pydantic_messages_to_anthropic_messages([resp])
    assert out == [{"role": "assistant", "content": api_content}]


def test_anthropic_thinking_text_tool_use_round_trip_batch() -> None:
    api_content = [
        {"type": "thinking", "thinking": "reason", "signature": "s1"},
        {"type": "text", "text": "Here is the answer."},
        {
            "type": "tool_use",
            "id": "toolu_02",
            "name": "glob",
            "input": {"pattern": "*.py"},
        },
    ]
    resp = anthropic_completion_to_model_response({"content": api_content})
    assert [type(p).__name__ for p in resp.parts] == [
        "ThinkingPart",
        "TextPart",
        "ToolCallPart",
    ]
    out = pydantic_messages_to_anthropic_messages([resp])
    assert out == [{"role": "assistant", "content": api_content}]


def test_display_salvage_from_thinking_not_in_history() -> None:
    """Thinking→text salvage is UI-only; history keeps ``ThinkingPart``."""
    api_content = [{"type": "thinking", "thinking": 'pick {"intent": "GREETING"} ok'}]
    resp = anthropic_completion_to_model_response({"content": api_content})
    assert len(resp.parts) == 1
    assert isinstance(resp.parts[0], ThinkingPart)
    assert _display_text_from_model_response(resp) == '{"intent": "GREETING"}'
    out = pydantic_messages_to_anthropic_messages([resp])
    assert out[0]["content"] == api_content


def test_display_no_salvage_when_tool_use_present() -> None:
    api_content = [
        {"type": "thinking", "thinking": "should not surface"},
        {"type": "tool_use", "id": "t1", "name": "read", "input": {}},
    ]
    resp = anthropic_completion_to_model_response({"content": api_content})
    assert _display_text_from_model_response(resp) == ""


def _openai_msg(message: dict[str, Any]) -> dict[str, Any]:
    return {"choices": [{"message": message}]}


def test_openai_recovers_xml_tool_call_from_content() -> None:
    """XML tool calls in ``content`` become a ToolCallPart, not leaked/stripped text.

    Regression for transcript-review-2026-06-22: MiniMax emitted ``<invoke>`` XML inside
    ``content`` on the chat_completions wire; outbound hygiene then stripped the whole body,
    emptying an otherwise-valid turn (``sanitizer_emptied dropped=2351``).
    """
    resp = openai_completion_to_model_response(
        _openai_msg(
            {
                "content": (
                    '<invoke name="read"><parameter name="file_path">a.py</parameter></invoke>'
                ),
            },
        ),
    )
    tool_parts = [p for p in resp.parts if isinstance(p, ToolCallPart)]
    assert len(tool_parts) == 1
    assert tool_parts[0].tool_name == "read"
    assert json.loads(tool_parts[0].args_as_json_str()) == {"file_path": "a.py"}
    assert not any(isinstance(p, TextPart) and "<invoke" in p.content for p in resp.parts)


def test_openai_maps_reasoning_content_to_thinking() -> None:
    """``reasoning_content`` is mapped to a ThinkingPart ordered before visible text."""
    resp = openai_completion_to_model_response(
        _openai_msg({"reasoning_content": "weighing options", "content": "the answer"}),
    )
    assert [type(p).__name__ for p in resp.parts] == ["ThinkingPart", "TextPart"]
    assert _display_text_from_model_response(resp) == "the answer"


def test_openai_native_tool_calls_preserved_over_xml_recovery() -> None:
    """Structured ``tool_calls`` short-circuit XML recovery (no double-parsing)."""
    resp = openai_completion_to_model_response(
        _openai_msg(
            {
                "content": "ignored <invoke name='glob'></invoke>",
                "tool_calls": [
                    {"id": "c1", "function": {"name": "read", "arguments": "{}"}},
                ],
            },
        ),
    )
    tool_parts = [p for p in resp.parts if isinstance(p, ToolCallPart)]
    assert [p.tool_name for p in tool_parts] == ["read"]
    assert tool_parts[0].tool_call_id == "c1"


def test_bedrock_converse_fixture_text_part() -> None:
    data = _load("bedrock_converse_response_text.json")
    resp = bedrock_converse_to_model_response(data)
    assert any(p.content == "Bedrock reply." for p in resp.parts if hasattr(p, "content"))


def test_bedrock_messages_from_anthropic_projection() -> None:
    msgs = [ModelRequest(parts=[UserPromptPart(content="ping")])]
    out = pydantic_messages_to_bedrock_converse(msgs)
    assert out == [{"role": "user", "content": [{"text": "ping"}]}]


@pytest.mark.asyncio
async def test_anthropic_messages_transport_stream_uses_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = [_load("openai_stream_chunk.json")]

    async def fake_sse(**kwargs: object):
        assert kwargs["path"] == "/llm/anthropic/messages"
        for chunk in chunks:
            yield chunk

    monkeypatch.setattr(
        "sevn.agent.providers.transport.transport_http.iter_llm_sse",
        fake_sse,
    )
    transport = AnthropicMessagesTransport(proxy_base_url="http://proxy.test")
    collected: list[dict[str, Any]] = []
    async for event in transport.stream({"model": "claude-test"}):
        collected.append(event)
    assert collected == chunks


@pytest.mark.asyncio
async def test_bedrock_transport_stream_uses_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [_load("openai_stream_chunk.json")]

    async def fake_sse(**kwargs: object):
        assert kwargs["path"] == "/llm/bedrock/converse"
        for chunk in chunks:
            yield chunk

    monkeypatch.setattr(
        "sevn.agent.providers.transport.transport_http.iter_llm_sse",
        fake_sse,
    )
    transport = BedrockTransport(proxy_base_url="http://proxy.test")
    collected: list[dict[str, Any]] = []
    async for event in transport.stream({"modelId": "anthropic.claude-3"}):
        collected.append(event)
    assert collected == chunks


@pytest.mark.asyncio
async def test_anthropic_complete_stream_yields_growing_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``complete_stream`` parses Anthropic SSE into real deltas + a final payload.

    The proxy passes the upstream ``text/event-stream`` through verbatim, so the
    transport reconstructs ``content_block_delta`` → ``text_delta`` frames into
    incremental :class:`StreamTextDelta` events and a terminal :class:`StreamFinal`
    matching ``complete``'s shape (so the tier-B converter can run on it).
    """
    events = [
        {"type": "message_start", "message": {"model": "MiniMax-M3", "usage": {"input_tokens": 5}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hel"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "!"}},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 3},
        },
        {"type": "message_stop"},
    ]

    async def fake_sse(**kwargs: object):
        assert kwargs["path"] == "/llm/anthropic/messages"
        body = kwargs["body"]
        assert isinstance(body, dict)
        assert body.get("stream") is True
        for ev in events:
            yield ev

    monkeypatch.setattr(
        "sevn.agent.providers.transport.transport_http.iter_llm_sse",
        fake_sse,
    )
    transport = AnthropicMessagesTransport(proxy_base_url="http://proxy.test")
    deltas: list[str] = []
    final: StreamFinal | None = None
    async for chunk in transport.complete_stream({"model": "minimax/MiniMax-M3"}):
        if isinstance(chunk, StreamTextDelta):
            deltas.append(chunk.text)
        else:
            final = chunk

    # Real per-frame deltas, not one final blob.
    assert deltas == ["Hel", "lo", "!"]
    accumulations = ["".join(deltas[: i + 1]) for i in range(len(deltas))]
    assert accumulations == ["Hel", "Hello", "Hello!"]
    assert final is not None
    # Final payload mirrors a non-streaming ``complete`` body → converter works.
    resp = anthropic_completion_to_model_response(final.response)
    assert any(getattr(p, "content", None) == "Hello!" for p in resp.parts)
    assert final.response["usage"] == {"input_tokens": 5, "output_tokens": 3}


@pytest.mark.asyncio
async def test_anthropic_complete_stream_thinking_tool_use_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Streaming ``StreamFinal`` uses the same ordered-part converter as batch."""
    events = [
        {
            "type": "message_start",
            "message": {"model": "MiniMax-M3", "usage": {"input_tokens": 2}},
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "stream plan"},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_stream",
                "name": "read",
                "input": {},
            },
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"file_path": "b.py"}'},
        },
        {"type": "content_block_stop", "index": 1},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 4},
        },
        {"type": "message_stop"},
    ]

    async def fake_sse(**kwargs: object):
        for ev in events:
            yield ev

    monkeypatch.setattr(
        "sevn.agent.providers.transport.transport_http.iter_llm_sse",
        fake_sse,
    )
    transport = AnthropicMessagesTransport(proxy_base_url="http://proxy.test")
    final: StreamFinal | None = None
    async for chunk in transport.complete_stream({"model": "minimax/MiniMax-M3"}):
        if isinstance(chunk, StreamFinal):
            final = chunk

    assert final is not None
    stream_content = final.response["content"]
    assert stream_content[0] == {"type": "thinking", "thinking": "stream plan"}
    assert stream_content[1]["type"] == "tool_use"
    assert stream_content[1]["name"] == "read"
    assert stream_content[1]["input"] == {"file_path": "b.py"}
    resp = anthropic_completion_to_model_response(final.response)
    assert [type(p).__name__ for p in resp.parts] == ["ThinkingPart", "ToolCallPart"]
    out = pydantic_messages_to_anthropic_messages([resp])
    assert out == [{"role": "assistant", "content": stream_content}]


@pytest.mark.asyncio
async def test_openai_complete_stream_assembles_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAI chat SSE with streamed ``tool_calls`` reassembles into a final payload."""
    events = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "function": {"name": "read", "arguments": '{"fi'},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'le":"a.py"}'}}]}}
            ]
        },
    ]

    async def fake_sse(**kwargs: object):
        for ev in events:
            yield ev

    monkeypatch.setattr(
        "sevn.agent.providers.transport.transport_http.iter_llm_sse",
        fake_sse,
    )
    transport = ChatCompletionsTransport(proxy_base_url="http://proxy.test")
    final: StreamFinal | None = None
    async for chunk in transport.complete_stream({"model": "openai/gpt"}):
        if isinstance(chunk, StreamFinal):
            final = chunk
    assert final is not None
    tc = final.response["choices"][0]["message"]["tool_calls"][0]
    assert tc["function"] == {"name": "read", "arguments": '{"file":"a.py"}'}


@pytest.mark.asyncio
async def test_bedrock_complete_stream_not_implemented() -> None:
    """Bedrock has no SSE reconstruction yet → ``complete_stream`` raises (callers fall back)."""
    transport = BedrockTransport(proxy_base_url="http://proxy.test")
    with pytest.raises(NotImplementedError):
        async for _ in transport.complete_stream({"modelId": "anthropic.claude-3"}):
            pass


def test_supports_streaming_capability_per_transport() -> None:
    """``supports_streaming`` gates the tier-B ``node.stream`` tap per wire.

    Anthropic/MiniMax (and its ``AnthropicMessagesTransport`` alias) plus OpenAI
    chat/responses now reconstruct real SSE via ``complete_stream`` → ``True``.
    Bedrock Converse has no streaming reconstruction yet → ``False``
    (`specs/05-llm-transports.md` §2.3, `specs/14-executor-tier-b.md` §2.3).
    """
    assert AnthropicTransport().supports_streaming is True
    assert AnthropicMessagesTransport().supports_streaming is True
    assert ChatCompletionsTransport().supports_streaming is True
    assert ResponsesApiTransport().supports_streaming is True
    assert BedrockTransport().supports_streaming is False
