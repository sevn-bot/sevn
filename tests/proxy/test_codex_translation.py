"""Chat-completions ↔ Responses translation tests (W1.9 — D7)."""

from __future__ import annotations

import pathlib

import pytest

_SAMPLE_CHAT_REQUEST: dict[str, object] = {
    "model": "openai/gpt-4o",
    "messages": [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
    ],
    "stream": False,
}

_SAMPLE_RESPONSES_BODY: dict[str, object] = {
    "id": "resp_codex_1",
    "object": "response",
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Hi there!"}],
        },
    ],
}

_SAMPLE_SSE_LINES = [
    'data: {"type":"response.output_text.delta","delta":"Hi"}',
    'data: {"type":"response.output_text.delta","delta":" there!"}',
    "data: [DONE]",
]


def test_chat_to_responses_request_maps_messages_and_model() -> None:
    """Internal chat-completions body translates to Responses schema."""
    from sevn.proxy.codex_translation import translate_chat_to_responses_request

    out = translate_chat_to_responses_request(_SAMPLE_CHAT_REQUEST)
    assert out.get("store") is False
    assert out.get("instructions")
    assert "reasoning.encrypted_content" in (out.get("include") or [])
    assert out.get("model") == "gpt-4o" or "gpt-4o" in str(out.get("model", ""))


def test_chat_to_responses_request_preserves_stream_flag() -> None:
    """Streaming chat request sets Responses stream mode."""
    from sevn.proxy.codex_translation import translate_chat_to_responses_request

    req = {**_SAMPLE_CHAT_REQUEST, "stream": True}
    out = translate_chat_to_responses_request(req)
    assert out.get("stream") is True


def test_responses_to_chat_completion_maps_assistant_text() -> None:
    """Responses JSON body round-trips to chat-completions completion shape."""
    from sevn.proxy.codex_translation import translate_responses_to_chat_completion

    chat = translate_responses_to_chat_completion(_SAMPLE_RESPONSES_BODY)
    assert chat.get("object") == "chat.completion"
    choices = chat.get("choices")
    assert isinstance(choices, list)
    assert choices
    message = choices[0].get("message", {})
    assert message.get("role") == "assistant"
    assert "Hi there!" in str(message.get("content", ""))


def test_responses_sse_to_chat_stream_yields_deltas() -> None:
    """SSE Responses stream translates to chat-completions ``data:`` chunks."""
    from sevn.proxy.codex_translation import translate_responses_sse_to_chat_stream

    raw_sse = "\n".join(_SAMPLE_SSE_LINES) + "\n"
    chunks = list(translate_responses_sse_to_chat_stream(raw_sse))
    assert chunks
    joined = "".join(chunks)
    assert "delta" in joined or "content" in joined


def test_roundtrip_chat_request_response_non_stream() -> None:
    """Non-streaming turn: chat request → Responses → chat completion."""
    from sevn.proxy.codex_translation import (
        translate_chat_to_responses_request,
        translate_responses_to_chat_completion,
    )

    responses_req = translate_chat_to_responses_request(_SAMPLE_CHAT_REQUEST)
    assert responses_req.get("store") is False
    chat = translate_responses_to_chat_completion(_SAMPLE_RESPONSES_BODY)
    assert chat.get("choices")


@pytest.mark.parametrize("bad_body", [{}, {"output": []}, {"output": "nope"}])
def test_responses_to_chat_raises_on_invalid_body(bad_body: dict[str, object]) -> None:
    """Invalid Responses payloads raise a translation error."""
    from sevn.proxy.codex_translation import translate_responses_to_chat_completion

    with pytest.raises((ValueError, KeyError, TypeError)):
        translate_responses_to_chat_completion(bad_body)


def test_responses_sse_parses_json_lines_only() -> None:
    """SSE parser ignores blank lines and non-data prefixes."""
    from sevn.proxy.codex_translation import translate_responses_sse_to_chat_stream

    raw = ":\n\n" + "\n".join(_SAMPLE_SSE_LINES)
    chunks = list(translate_responses_sse_to_chat_stream(raw))
    assert len(chunks) >= 1


# --- aggregate_responses_sse (non-streaming caller path) ---------------------

_COMPLETED_SSE = (
    'data: {"type":"response.created","response":{"id":"r1"}}\n\n'
    'data: {"type":"response.output_text.delta","delta":"Hi"}\n\n'
    'data: {"type":"response.output_text.delta","delta":" there!"}\n\n'
    'data: {"type":"response.completed","response":'
    '{"id":"r1","model":"gpt-5.5","output":[{"type":"message","role":"assistant",'
    '"content":[{"type":"output_text","text":"Hi there!"}]}]}}\n\n'
    "data: [DONE]\n\n"
)


def test_aggregate_responses_sse_returns_terminal_object() -> None:
    """A ``response.completed`` event yields its full ``response`` payload."""
    from sevn.proxy.codex_translation import aggregate_responses_sse

    body = aggregate_responses_sse(_COMPLETED_SSE)
    assert body["id"] == "r1"
    assert body["model"] == "gpt-5.5"
    assert body["output"][0]["content"][0]["text"] == "Hi there!"


def test_aggregate_responses_sse_then_translate_to_chat() -> None:
    """The aggregated object feeds straight into the chat-completion translation."""
    from sevn.proxy.codex_translation import (
        aggregate_responses_sse,
        translate_responses_to_chat_completion,
    )

    chat = translate_responses_to_chat_completion(aggregate_responses_sse(_COMPLETED_SSE))
    assert chat["choices"][0]["message"]["content"] == "Hi there!"


def test_aggregate_responses_sse_falls_back_to_deltas() -> None:
    """Without a terminal event, output_text deltas are concatenated."""
    from sevn.proxy.codex_translation import aggregate_responses_sse

    sse = (
        'data: {"type":"response.output_text.delta","delta":"Hi"}\n\n'
        'data: {"type":"response.output_text.delta","delta":" there!"}\n\n'
    )
    body = aggregate_responses_sse(sse)
    assert body["output"][0]["content"][0]["text"] == "Hi there!"


def test_aggregate_responses_sse_surfaces_tool_calls() -> None:
    """A function_call ``output_item.done`` surfaces in ``output`` (tool calls).

    Codex delivers the completed function call via ``output_item.done`` while the
    terminal ``response.completed`` carries an empty ``output``.
    """
    from sevn.proxy.codex_translation import aggregate_responses_sse

    sse = (
        'data: {"type":"response.output_item.added","output_index":0,"item":'
        '{"type":"function_call","name":"get_weather","call_id":"call_1"}}\n\n'
        'data: {"type":"response.output_item.done","output_index":0,"item":'
        '{"type":"function_call","name":"get_weather",'
        '"arguments":"{\\"city\\":\\"SF\\"}","call_id":"call_1"}}\n\n'
        'data: {"type":"response.completed","response":{"id":"r2","output":[]}}\n\n'
        "data: [DONE]\n\n"
    )
    body = aggregate_responses_sse(sse)
    output = body["output"]
    assert output[0]["type"] == "function_call"
    assert output[0]["name"] == "get_weather"
    assert output[0]["call_id"] == "call_1"


def test_aggregate_responses_sse_raises_on_empty_stream() -> None:
    """A stream with no terminal object and no text deltas raises ``ValueError``."""
    from sevn.proxy.codex_translation import aggregate_responses_sse

    with pytest.raises(ValueError, match="no terminal object"):
        aggregate_responses_sse(":\n\ndata: [DONE]\n\n")


# --- aggregate_responses_sse (output_item.done reconstruction) ---------------
#
# The live 502 root cause: Codex sends ``response.completed`` with an EMPTY
# ``response.output`` list and delivers the real assistant content via
# ``response.output_item.done`` events (each carrying a completed ``item``).
# Aggregation must reconstruct ``output[]`` from those per-item events.

_CODEX_STREAM_FIXTURE = (
    pathlib.Path(__file__).parent / "fixtures" / "codex_responses_stream.sse"
).read_text()


def test_aggregate_reconstructs_output_from_item_done_events() -> None:
    """Real captured Codex stream: message item is reconstructed from output_item.done.

    The terminal ``response.completed`` carries ``output == []``; the message and
    reasoning items arrive as ``response.output_item.done`` events. Aggregation must
    splice them back into the envelope's ``output``.
    """
    from sevn.proxy.codex_translation import aggregate_responses_sse

    body = aggregate_responses_sse(_CODEX_STREAM_FIXTURE)
    # Envelope metadata comes from ``response.completed``.
    assert body["id"] == "resp_SANITIZED_0001"
    assert body["model"] == "gpt-5.5"
    types = [item.get("type") for item in body["output"]]
    assert "message" in types
    message = next(item for item in body["output"] if item.get("type") == "message")
    assert message["content"][0]["text"] == "hello there friend"


def test_aggregate_captured_stream_translates_to_chat() -> None:
    """The reconstructed object translates to chat content ``hello there friend``."""
    from sevn.proxy.codex_translation import (
        aggregate_responses_sse,
        translate_responses_to_chat_completion,
    )

    chat = translate_responses_to_chat_completion(aggregate_responses_sse(_CODEX_STREAM_FIXTURE))
    assert chat["choices"][0]["message"]["content"] == "hello there friend"
    assert chat["choices"][0]["finish_reason"] == "stop"


def test_aggregate_empty_terminal_output_uses_item_done_message() -> None:
    """The exact live bug: empty ``response.completed.output`` + a message item_done.

    Under the old behavior (return ``response.completed.response`` verbatim), this
    stream yields ``output == []`` and the translator raises a 502. Aggregation now
    recovers the message from the ``output_item.done`` event.
    """
    from sevn.proxy.codex_translation import (
        aggregate_responses_sse,
        translate_responses_to_chat_completion,
    )

    sse = (
        'data: {"type":"response.output_item.done","output_index":0,"item":'
        '{"type":"message","role":"assistant","status":"completed",'
        '"content":[{"type":"output_text","text":"recovered"}]}}\n\n'
        'data: {"type":"response.completed","response":'
        '{"id":"r_empty","model":"gpt-5.5","output":[]}}\n\n'
        "data: [DONE]\n\n"
    )
    body = aggregate_responses_sse(sse)
    assert body["id"] == "r_empty"
    assert body["output"], "output must be reconstructed from output_item.done"
    chat = translate_responses_to_chat_completion(body)
    assert chat["choices"][0]["message"]["content"] == "recovered"


def test_aggregate_function_call_item_done_survives_to_tool_calls() -> None:
    """A ``function_call`` output_item.done aggregates into chat ``tool_calls``.

    Terminal output is empty; the function call arrives via ``output_item.done``.
    """
    from sevn.proxy.codex_translation import (
        aggregate_responses_sse,
        translate_responses_to_chat_completion,
    )

    sse = (
        'data: {"type":"response.output_item.added","output_index":0,"item":'
        '{"type":"function_call","name":"get_weather","call_id":"call_fc_1"}}\n\n'
        'data: {"type":"response.output_item.done","output_index":0,"item":'
        '{"type":"function_call","name":"get_weather",'
        '"arguments":"{\\"city\\":\\"SF\\"}","call_id":"call_fc_1"}}\n\n'
        'data: {"type":"response.completed","response":'
        '{"id":"r_fc","model":"gpt-5.5","output":[]}}\n\n'
        "data: [DONE]\n\n"
    )
    body = aggregate_responses_sse(sse)
    assert body["output"][0]["type"] == "function_call"
    assert body["output"][0]["arguments"] == '{"city":"SF"}'
    chat = translate_responses_to_chat_completion(body)
    tool_calls = chat["choices"][0]["message"]["tool_calls"]
    assert tool_calls[0]["id"] == "call_fc_1"
    assert tool_calls[0]["function"]["name"] == "get_weather"
    assert tool_calls[0]["function"]["arguments"] == '{"city":"SF"}'
    assert chat["choices"][0]["finish_reason"] == "tool_calls"


# --- Request: tool definitions / tool_choice --------------------------------

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the weather.",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
        },
    },
]


def test_chat_to_responses_flattens_tools() -> None:
    """OpenAI nested tools flatten to the Codex/Responses ``function`` shape."""
    from sevn.proxy.codex_translation import translate_chat_to_responses_request

    out = translate_chat_to_responses_request(
        {**_SAMPLE_CHAT_REQUEST, "tools": _TOOLS},
    )
    tools = out["tools"]
    assert tools[0] == {
        "type": "function",
        "name": "get_weather",
        "description": "Get the weather.",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
    }
    # Not nested under "function".
    assert "function" not in tools[0]


def test_chat_to_responses_passes_tool_choice() -> None:
    """``tool_choice`` passes through; a forced function choice is flattened."""
    from sevn.proxy.codex_translation import translate_chat_to_responses_request

    auto = translate_chat_to_responses_request(
        {**_SAMPLE_CHAT_REQUEST, "tools": _TOOLS, "tool_choice": "auto"},
    )
    assert auto["tool_choice"] == "auto"

    forced = translate_chat_to_responses_request(
        {
            **_SAMPLE_CHAT_REQUEST,
            "tools": _TOOLS,
            "tool_choice": {"type": "function", "function": {"name": "get_weather"}},
        },
    )
    assert forced["tool_choice"] == {"type": "function", "name": "get_weather"}


def test_chat_to_responses_omits_tools_when_absent() -> None:
    """A request with no tools carries neither ``tools`` nor ``tool_choice``."""
    from sevn.proxy.codex_translation import translate_chat_to_responses_request

    out = translate_chat_to_responses_request(_SAMPLE_CHAT_REQUEST)
    assert "tools" not in out
    assert "tool_choice" not in out


# --- Request: assistant tool_calls + tool results ---------------------------


def test_chat_to_responses_assistant_tool_calls_become_function_call_items() -> None:
    """A prior assistant ``tool_calls`` message becomes ``function_call`` input items."""
    from sevn.proxy.codex_translation import translate_chat_to_responses_request

    out = translate_chat_to_responses_request(
        {
            "model": "openai/gpt-4o",
            "messages": [
                {"role": "user", "content": "weather?"},
                {
                    "role": "assistant",
                    "content": "Let me check.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"city":"SF"}'},
                        },
                    ],
                },
            ],
        },
    )
    items = out["input"]
    # user message, assistant text message, then the function_call item.
    types = [item.get("type") for item in items]
    assert types == ["message", "message", "function_call"]
    fc = items[2]
    assert fc == {
        "type": "function_call",
        "call_id": "call_1",
        "name": "get_weather",
        "arguments": '{"city":"SF"}',
    }


def test_chat_to_responses_tool_result_becomes_function_call_output() -> None:
    """A ``role:"tool"`` message becomes a ``function_call_output`` item (not a message)."""
    from sevn.proxy.codex_translation import translate_chat_to_responses_request

    out = translate_chat_to_responses_request(
        {
            "model": "openai/gpt-4o",
            "messages": [
                {"role": "tool", "tool_call_id": "call_1", "content": "72F and sunny"},
            ],
        },
    )
    items = out["input"]
    assert items == [
        {"type": "function_call_output", "call_id": "call_1", "output": "72F and sunny"},
    ]
    # The old bug produced {"type":"message","role":"tool"}; ensure it is gone.
    assert all(item.get("role") != "tool" for item in items)


def test_chat_to_responses_assistant_tool_call_only_has_no_text_item() -> None:
    """An assistant message with only tool_calls (no text) yields just function_call."""
    from sevn.proxy.codex_translation import translate_chat_to_responses_request

    out = translate_chat_to_responses_request(
        {
            "model": "openai/gpt-4o",
            "messages": [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_9",
                            "type": "function",
                            "function": {"name": "f", "arguments": "{}"},
                        },
                    ],
                },
            ],
        },
    )
    items = out["input"]
    assert [i.get("type") for i in items] == ["function_call"]


def test_chat_to_responses_full_tool_history_round_trip() -> None:
    """A mixed user/assistant-tool_calls/tool-result history maps in order."""
    from sevn.proxy.codex_translation import translate_chat_to_responses_request

    out = translate_chat_to_responses_request(
        {
            "model": "openai/gpt-4o",
            "messages": [
                {"role": "system", "content": "Be helpful."},
                {"role": "user", "content": "weather in SF?"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"city":"SF"}'},
                        },
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "72F"},
                {"role": "user", "content": "thanks"},
            ],
        },
    )
    types = [item.get("type") for item in out["input"]]
    assert types == ["message", "function_call", "function_call_output", "message"]
    assert out["instructions"] == "Be helpful."


# --- Buffered response: function_call → tool_calls --------------------------


def test_responses_to_chat_maps_function_call_to_tool_calls() -> None:
    """A Responses ``function_call`` output maps to chat ``tool_calls`` + finish reason."""
    from sevn.proxy.codex_translation import translate_responses_to_chat_completion

    chat = translate_responses_to_chat_completion(
        {
            "id": "r1",
            "model": "gpt-5.5",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "get_weather",
                    "arguments": '{"city":"SF"}',
                },
            ],
        },
    )
    choice = chat["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    tool_calls = choice["message"]["tool_calls"]
    assert tool_calls == [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city":"SF"}'},
        },
    ]
    assert choice["message"]["content"] is None


def test_responses_to_chat_text_and_tool_call_co_occur() -> None:
    """Assistant text and a tool call in the same response both appear."""
    from sevn.proxy.codex_translation import translate_responses_to_chat_completion

    chat = translate_responses_to_chat_completion(
        {
            "id": "r1",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Checking..."}],
                },
                {
                    "type": "function_call",
                    "call_id": "call_2",
                    "name": "f",
                    "arguments": "{}",
                },
            ],
        },
    )
    choice = chat["choices"][0]
    assert choice["message"]["content"] == "Checking..."
    assert choice["message"]["tool_calls"][0]["id"] == "call_2"
    assert choice["finish_reason"] == "tool_calls"


def test_responses_to_chat_text_only_unchanged() -> None:
    """A text-only response keeps ``finish_reason="stop"`` and no ``tool_calls``."""
    from sevn.proxy.codex_translation import translate_responses_to_chat_completion

    chat = translate_responses_to_chat_completion(_SAMPLE_RESPONSES_BODY)
    choice = chat["choices"][0]
    assert choice["finish_reason"] == "stop"
    assert "tool_calls" not in choice["message"]
    assert choice["message"]["content"] == "Hi there!"


def test_responses_to_chat_function_call_id_fallback() -> None:
    """When ``call_id`` is absent the item ``id`` is used as the tool-call id."""
    from sevn.proxy.codex_translation import translate_responses_to_chat_completion

    chat = translate_responses_to_chat_completion(
        {
            "id": "r1",
            "output": [{"type": "function_call", "id": "fc_1", "name": "f", "arguments": "{}"}],
        },
    )
    assert chat["choices"][0]["message"]["tool_calls"][0]["id"] == "fc_1"


# --- Streaming response: function_call deltas -------------------------------

_TOOL_STREAM_SSE = (
    'data: {"type":"response.output_item.added","output_index":0,'
    '"item":{"type":"function_call","call_id":"call_1","name":"get_weather"}}\n\n'
    'data: {"type":"response.function_call_arguments.delta","output_index":0,'
    '"delta":"{\\"city\\":"}\n\n'
    'data: {"type":"response.function_call_arguments.delta","output_index":0,'
    '"delta":"\\"SF\\"}"}\n\n'
    'data: {"type":"response.completed","response":{"id":"r1","output":['
    '{"type":"function_call","call_id":"call_1","name":"get_weather",'
    '"arguments":"{\\"city\\":\\"SF\\"}"}]}}\n\n'
    "data: [DONE]\n\n"
)


def test_stream_translates_function_call_deltas() -> None:
    """A Codex tool-call SSE stream yields ordered chat tool_call deltas + terminal."""
    import json as _json

    from sevn.proxy.codex_translation import translate_responses_sse_to_chat_stream

    chunks = list(translate_responses_sse_to_chat_stream(_TOOL_STREAM_SSE))
    payloads = [
        _json.loads(c[len("data: ") :].strip())
        for c in chunks
        if c.startswith("data: ") and "[DONE]" not in c
    ]
    deltas = [p["choices"][0]["delta"] for p in payloads]

    # First chunk opens the tool call with id + name.
    first_tc = deltas[0]["tool_calls"][0]
    assert first_tc["index"] == 0
    assert first_tc["id"] == "call_1"
    assert first_tc["function"]["name"] == "get_weather"

    # Argument deltas accumulate to the full JSON string.
    arg_pieces = "".join(
        tc["function"]["arguments"]
        for d in deltas
        for tc in d.get("tool_calls", [])
        if "arguments" in tc.get("function", {})
    )
    assert arg_pieces == '{"city":"SF"}'

    # Terminal chunk carries finish_reason="tool_calls".
    assert payloads[-1]["choices"][0]["finish_reason"] == "tool_calls"
    assert chunks[-1] == "data: [DONE]\n\n"


def test_stream_text_only_finishes_with_stop() -> None:
    """A text-only stream still finishes with ``finish_reason="stop"`` (no tool calls)."""
    import json as _json

    from sevn.proxy.codex_translation import translate_responses_sse_to_chat_stream

    sse = (
        'data: {"type":"response.output_text.delta","delta":"Hi"}\n\n'
        'data: {"type":"response.completed","response":{"id":"r1","output":[]}}\n\n'
        "data: [DONE]\n\n"
    )
    chunks = list(translate_responses_sse_to_chat_stream(sse))
    payloads = [
        _json.loads(c[len("data: ") :].strip())
        for c in chunks
        if c.startswith("data: ") and "[DONE]" not in c
    ]
    assert payloads[0]["choices"][0]["delta"].get("content") == "Hi"
    assert payloads[-1]["choices"][0]["finish_reason"] == "stop"
    assert all("tool_calls" not in p["choices"][0]["delta"] for p in payloads)


# --- Multi-line ``data:`` SSE framing (live Codex regression) ----------------
#
# Real Codex Responses events spread one event's JSON across multiple ``data:``
# lines (the SSE multi-line ``data`` field). The large terminal
# ``response.completed`` event — carrying ``reasoning.encrypted_content`` — is the
# common offender. A line-by-line parser ``json.loads``-es each partial ``data:``
# line, fails, silently drops them, finds no terminal object, and raises (the live
# 502 "non-stream aggregation failed"). These fixtures encode one event per
# ``\n\n`` block but split the event JSON across several ``data:`` continuation
# lines within the block, exactly as the upstream stream does.


def _multiline_data_event(payload: dict[str, object], *, splits: int = 3) -> str:
    """Serialize one Responses event into a multi-line ``data:`` SSE block.

    Renders the event JSON with newline-separated tokens (pretty-printed) and emits
    each physical line as its own ``data:`` continuation line. Per the SSE spec a
    parser must rejoin the block's ``data:`` lines with ``\\n``; doing so here
    reconstructs the original (still-valid) JSON. This mirrors how Codex frames a
    single large event whose payload spans multiple ``data:`` lines — exactly the
    framing the old line-by-line parser could not decode.

    The ``splits`` argument is accepted for call-site readability but the real line
    count is driven by the JSON structure; callers only rely on >1 ``data:`` line.
    """
    import json as _json

    del splits
    text = _json.dumps(payload, indent=1)
    return "".join(f"data: {line}\n" for line in text.split("\n"))


_REASONING_BLOB = "Zm9vYmFy" * 64  # stand-in for reasoning.encrypted_content
_TERMINAL_RESPONSE: dict[str, object] = {
    "id": "resp_multiline_1",
    "model": "gpt-5.5",
    "output": [
        {
            "type": "reasoning",
            "encrypted_content": _REASONING_BLOB,
            "summary": [],
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Hello from Codex!"}],
        },
    ],
}

_MULTILINE_COMPLETED_SSE = (
    _multiline_data_event({"type": "response.created", "response": {"id": "resp_multiline_1"}})
    + "\n"
    + 'data: {"type":"response.output_text.delta","delta":"Hello "}\n\n'
    + 'data: {"type":"response.output_text.delta","delta":"from Codex!"}\n\n'
    + _multiline_data_event(
        {"type": "response.completed", "response": _TERMINAL_RESPONSE}, splits=6
    )
    + "\n"
    + "data: [DONE]\n\n"
)


def test_aggregate_responses_sse_handles_multiline_data_field() -> None:
    """Terminal ``response.completed`` split across multiple ``data:`` lines aggregates.

    This is the live 502 regression: the old line-by-line parser dropped every
    partial ``data:`` line of the terminal event and raised. The block parser joins
    the lines and recovers the full Responses object.
    """
    from sevn.proxy.codex_translation import aggregate_responses_sse

    body = aggregate_responses_sse(_MULTILINE_COMPLETED_SSE)
    assert body["id"] == "resp_multiline_1"
    assert body["model"] == "gpt-5.5"
    # The reasoning blob survives intact (proves multi-line join, not truncation).
    assert body["output"][0]["encrypted_content"] == _REASONING_BLOB
    assert body["output"][1]["content"][0]["text"] == "Hello from Codex!"


def test_aggregate_multiline_then_translate_to_chat() -> None:
    """The multi-line aggregated object feeds the chat-completion translation."""
    from sevn.proxy.codex_translation import (
        aggregate_responses_sse,
        translate_responses_to_chat_completion,
    )

    chat = translate_responses_to_chat_completion(aggregate_responses_sse(_MULTILINE_COMPLETED_SSE))
    assert chat["choices"][0]["message"]["content"] == "Hello from Codex!"
    assert chat["choices"][0]["finish_reason"] == "stop"


def test_aggregate_old_line_by_line_parser_would_fail() -> None:
    """Document the bug: a naive per-``data:``-line decode cannot recover the object.

    Asserts that decoding each ``data:`` line of the terminal event individually
    yields no terminal Responses object — i.e. the fixture genuinely exercises the
    multi-line framing the fix addresses (and the old parser would have raised).
    """
    import json as _json

    found_terminal = False
    for line in _MULTILINE_COMPLETED_SSE.splitlines():
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        data = stripped[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = _json.loads(data)
        except _json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "response.completed":
            found_terminal = True
    assert not found_terminal, "fixture must split the terminal event across data lines"


def test_aggregate_multiline_tool_call_terminal() -> None:
    """A multi-line terminal event carrying a ``function_call`` returns it verbatim."""
    from sevn.proxy.codex_translation import (
        aggregate_responses_sse,
        translate_responses_to_chat_completion,
    )

    terminal = {
        "type": "response.completed",
        "response": {
            "id": "resp_tool_ml",
            "output": [
                {
                    "type": "function_call",
                    "name": "get_weather",
                    "arguments": '{"city":"SF"}',
                    "call_id": "call_ml_1",
                }
            ],
        },
    }
    sse = (
        'data: {"type":"response.output_item.added","item":'
        '{"type":"function_call","name":"get_weather","call_id":"call_ml_1"}}\n\n'
        + _multiline_data_event(terminal, splits=5)
        + "\n"
        + "data: [DONE]\n\n"
    )
    body = aggregate_responses_sse(sse)
    assert body["output"][0]["call_id"] == "call_ml_1"
    chat = translate_responses_to_chat_completion(body)
    tool_calls = chat["choices"][0]["message"]["tool_calls"]
    assert tool_calls[0]["id"] == "call_ml_1"
    assert tool_calls[0]["function"]["name"] == "get_weather"
    assert chat["choices"][0]["finish_reason"] == "tool_calls"


def test_stream_handles_multiline_data_field() -> None:
    """Streaming translator yields correct deltas from multi-line ``data:`` events."""
    import json as _json

    from sevn.proxy.codex_translation import translate_responses_sse_to_chat_stream

    chunks = list(translate_responses_sse_to_chat_stream(_MULTILINE_COMPLETED_SSE))
    payloads = [
        _json.loads(c[len("data: ") :].strip())
        for c in chunks
        if c.startswith("data: ") and "[DONE]" not in c
    ]
    text = "".join(
        p["choices"][0]["delta"].get("content", "")
        for p in payloads
        if "content" in p["choices"][0]["delta"]
    )
    assert text == "Hello from Codex!"
    assert payloads[-1]["choices"][0]["finish_reason"] == "stop"
    assert chunks[-1] == "data: [DONE]\n\n"


def test_stream_multiline_terminal_tool_call_finishes_with_tool_calls() -> None:
    """A streamed multi-line terminal event with a tool call finishes as tool_calls."""
    import json as _json

    from sevn.proxy.codex_translation import translate_responses_sse_to_chat_stream

    terminal = {
        "type": "response.completed",
        "response": {
            "id": "r_ml",
            "output": [
                {
                    "type": "function_call",
                    "name": "f",
                    "arguments": "{}",
                    "call_id": "c1",
                }
            ],
        },
    }
    sse = _multiline_data_event(terminal, splits=4) + "\n" + "data: [DONE]\n\n"
    chunks = list(translate_responses_sse_to_chat_stream(sse))
    payloads = [
        _json.loads(c[len("data: ") :].strip())
        for c in chunks
        if c.startswith("data: ") and "[DONE]" not in c
    ]
    assert payloads[-1]["choices"][0]["finish_reason"] == "tool_calls"
