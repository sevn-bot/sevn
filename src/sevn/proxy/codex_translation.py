"""Chat-completions ↔ Codex Responses translation (W3.3 — D7).

Module: sevn.proxy.codex_translation
Depends: json, sevn.config.model_resolution

Exports:
    translate_chat_to_responses_request — map chat-completions JSON to Responses body.
    translate_responses_to_chat_completion — map Responses JSON to chat completion.
    translate_responses_sse_to_chat_stream — map Responses SSE to chat stream chunks.
    aggregate_responses_sse — assemble a terminal Responses object from Responses SSE.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

from sevn.config.model_resolution import resolve_wire_model_id

CODEX_DEFAULT_INSTRUCTIONS = "You are Codex, a coding assistant powered by OpenAI's GPT models."
"""Fallback ``instructions`` when the chat request has no system/developer message."""

_REASONING_INCLUDE = ["reasoning.encrypted_content"]


def _wire_model(chat_body: dict[str, Any]) -> str:
    """Return upstream model name from a chat-completions body.

    Args:
        chat_body (dict[str, Any]): Chat-completions request JSON.

    Returns:
        str: Wire model id with catalog prefix stripped when present.

    Examples:
        >>> _wire_model({"model": "openai/gpt-4o"})
        'gpt-4o'
    """
    model_raw = chat_body.get("model")
    model_id = str(model_raw).strip() if model_raw is not None else ""
    if not model_id:
        return ""
    wire = resolve_wire_model_id(model_id)
    if "/" in wire:
        return wire.split("/", 1)[1]
    return wire


def _extract_instructions(messages: list[Any]) -> tuple[str, list[dict[str, Any]]]:
    """Split system/developer text into ``instructions`` and remaining input.

    Args:
        messages (list[Any]): Chat ``messages`` array from the request body.

    Returns:
        tuple[str, list[dict[str, Any]]]: ``(instructions, input_messages)``.

    Examples:
        >>> instr, items = _extract_instructions([{"role": "user", "content": "hi"}])
        >>> isinstance(instr, str) and isinstance(items, list)
        True
    """
    instructions_parts: list[str] = []
    input_messages: list[dict[str, Any]] = []
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role", "")).strip().lower()
        content = raw.get("content")
        if role in ("system", "developer"):
            if isinstance(content, str) and content.strip():
                instructions_parts.append(content.strip())
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text")
                        if isinstance(text, str) and text.strip():
                            instructions_parts.append(text.strip())
            continue
        if role == "tool":
            input_messages.append(_tool_message_to_responses_item(raw))
        elif role == "assistant":
            input_messages.extend(_assistant_message_to_responses_items(raw))
        elif role == "user":
            input_messages.append(_chat_message_to_responses_item(raw))
    instructions = "\n\n".join(instructions_parts).strip() or CODEX_DEFAULT_INSTRUCTIONS
    return instructions, input_messages


def _chat_message_to_responses_item(message: dict[str, Any]) -> dict[str, Any]:
    """Map one chat message to a Responses ``input`` message item.

    Args:
        message (dict[str, Any]): One chat-completions message object.

    Returns:
        dict[str, Any]: Responses ``input`` message item.

    Examples:
        >>> _chat_message_to_responses_item({"role": "user", "content": "hi"})["role"]
        'user'
    """
    role = str(message.get("role", "user"))
    content = message.get("content")
    if isinstance(content, str):
        content_blocks = [
            {"type": "input_text" if role == "user" else "output_text", "text": content}
        ]
    elif isinstance(content, list):
        content_blocks = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str):
                        content_blocks.append(
                            {
                                "type": "input_text" if role == "user" else "output_text",
                                "text": text,
                            },
                        )
                elif block.get("type") == "input_text" or block.get("type") == "output_text":
                    content_blocks.append(dict(block))
    else:
        content_blocks = [{"type": "input_text", "text": str(content or "")}]
    return {"type": "message", "role": role, "content": content_blocks}


def _assistant_message_to_responses_items(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Map an assistant chat message (text and/or tool_calls) to Responses items.

    An assistant turn may carry plain text and/or a ``tool_calls`` array. The text
    (when present) becomes a ``message`` item with ``output_text`` content, and each
    OpenAI tool call (``{"id","type":"function","function":{"name","arguments"}}``)
    becomes a Responses ``function_call`` input item
    (``{"type":"function_call","call_id","name","arguments"}``).

    Args:
        message (dict[str, Any]): One assistant chat-completions message object.

    Returns:
        list[dict[str, Any]]: Ordered Responses ``input`` items (text first, then
        each function call).

    Examples:
        >>> items = _assistant_message_to_responses_items(
        ...     {
        ...         "role": "assistant",
        ...         "content": "Let me check.",
        ...         "tool_calls": [
        ...             {
        ...                 "id": "call_1",
        ...                 "type": "function",
        ...                 "function": {"name": "get_weather", "arguments": "{}"},
        ...             }
        ...         ],
        ...     }
        ... )
        >>> [i["type"] for i in items]
        ['message', 'function_call']
        >>> items[1]["call_id"]
        'call_1'
    """
    items: list[dict[str, Any]] = []
    content = message.get("content")
    has_text = (isinstance(content, str) and content) or (isinstance(content, list) and content)
    if has_text:
        items.append(_chat_message_to_responses_item(message))
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            fn = call.get("function")
            fn = fn if isinstance(fn, dict) else {}
            arguments = fn.get("arguments")
            items.append(
                {
                    "type": "function_call",
                    "call_id": str(call.get("id") or ""),
                    "name": str(fn.get("name") or ""),
                    "arguments": arguments if isinstance(arguments, str) else "{}",
                },
            )
    return items


def _tool_message_to_responses_item(message: dict[str, Any]) -> dict[str, Any]:
    """Map a ``role:"tool"`` chat message to a Responses ``function_call_output`` item.

    A chat tool result (``{"role":"tool","tool_call_id","content"}``) becomes a
    Responses ``function_call_output`` input item
    (``{"type":"function_call_output","call_id","output"}``). The ``output`` field
    is a string; list content blocks are flattened to their text.

    Args:
        message (dict[str, Any]): One ``role:"tool"`` chat-completions message.

    Returns:
        dict[str, Any]: A Responses ``function_call_output`` input item.

    Examples:
        >>> _tool_message_to_responses_item(
        ...     {"role": "tool", "tool_call_id": "call_1", "content": "72F"}
        ... )
        {'type': 'function_call_output', 'call_id': 'call_1', 'output': '72F'}
    """
    content = message.get("content")
    if isinstance(content, str):
        output = content
    elif isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        output = "".join(parts)
    else:
        output = str(content or "")
    return {
        "type": "function_call_output",
        "call_id": str(message.get("tool_call_id") or ""),
        "output": output,
    }


def _translate_tools(tools: Any) -> list[dict[str, Any]]:
    """Map OpenAI chat-completions ``tools`` to Codex Responses tool shape.

    OpenAI nests function tools as ``{"type":"function","function":{...}}``; the
    Responses API flattens them to ``{"type":"function","name","description",
    "parameters"}``. Non-function tool types are passed through unchanged.

    Args:
        tools (Any): The chat-completions ``tools`` array (or any value).

    Returns:
        list[dict[str, Any]]: Responses-shaped tool definitions (empty when none).

    Examples:
        >>> _translate_tools(
        ...     [
        ...         {
        ...             "type": "function",
        ...             "function": {
        ...                 "name": "get_weather",
        ...                 "description": "Get weather.",
        ...                 "parameters": {"type": "object"},
        ...             },
        ...         }
        ...     ]
        ... )
        [{'type': 'function', 'name': 'get_weather', 'description': 'Get weather.', 'parameters': {'type': 'object'}}]
    """
    out: list[dict[str, Any]] = []
    if not isinstance(tools, list):
        return out
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            fn = tool["function"]
            flat: dict[str, Any] = {"type": "function", "name": str(fn.get("name") or "")}
            if fn.get("description") is not None:
                flat["description"] = fn["description"]
            if fn.get("parameters") is not None:
                flat["parameters"] = fn["parameters"]
            if fn.get("strict") is not None:
                flat["strict"] = fn["strict"]
            out.append(flat)
        else:
            out.append(dict(tool))
    return out


def _translate_tool_choice(tool_choice: Any) -> Any:
    """Map an OpenAI ``tool_choice`` to its Responses equivalent.

    ``"auto"``/``"none"``/``"required"`` pass through unchanged. A forced function
    choice (``{"type":"function","function":{"name":...}}``) is flattened to the
    Responses form (``{"type":"function","name":...}``).

    Args:
        tool_choice (Any): The chat-completions ``tool_choice`` value.

    Returns:
        Any: The Responses ``tool_choice`` value.

    Examples:
        >>> _translate_tool_choice("auto")
        'auto'
        >>> _translate_tool_choice(
        ...     {"type": "function", "function": {"name": "get_weather"}}
        ... )
        {'type': 'function', 'name': 'get_weather'}
    """
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        fn = tool_choice.get("function")
        if isinstance(fn, dict):
            return {"type": "function", "name": str(fn.get("name") or "")}
    return tool_choice


def translate_chat_to_responses_request(chat_body: dict[str, Any]) -> dict[str, Any]:
    """Translate an internal chat-completions body to Codex Responses schema (D7).

    Maps system/developer text to ``instructions``; user/assistant/tool messages to
    Responses ``input`` items (assistant ``tool_calls`` become ``function_call``
    items and ``role:"tool"`` results become ``function_call_output`` items); and
    OpenAI ``tools``/``tool_choice`` to their flattened Responses equivalents.

    Args:
        chat_body (dict[str, Any]): OpenAI chat-completions request JSON.

    Returns:
        dict[str, Any]: Responses API body with ``store=false`` and Codex includes.

    Examples:
        >>> body = translate_chat_to_responses_request(
        ...     {"model": "openai/gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
        ... )
        >>> body["store"] is False
        True
        >>> tools_body = translate_chat_to_responses_request(
        ...     {
        ...         "model": "openai/gpt-4o",
        ...         "messages": [{"role": "user", "content": "hi"}],
        ...         "tools": [
        ...             {
        ...                 "type": "function",
        ...                 "function": {"name": "f", "parameters": {"type": "object"}},
        ...             }
        ...         ],
        ...     }
        ... )
        >>> tools_body["tools"][0]
        {'type': 'function', 'name': 'f', 'parameters': {'type': 'object'}}
    """
    messages_raw = chat_body.get("messages")
    messages = messages_raw if isinstance(messages_raw, list) else []
    instructions, input_messages = _extract_instructions(messages)
    out: dict[str, Any] = {
        "model": _wire_model(chat_body),
        "store": False,
        "instructions": instructions,
        "include": list(_REASONING_INCLUDE),
        "input": input_messages,
    }
    tools = _translate_tools(chat_body.get("tools"))
    if tools:
        out["tools"] = tools
    if "tool_choice" in chat_body:
        out["tool_choice"] = _translate_tool_choice(chat_body.get("tool_choice"))
    if chat_body.get("stream") is True:
        out["stream"] = True
    return out


def _assistant_text_from_responses(body: dict[str, Any]) -> str:
    """Extract assistant text from a Responses JSON body.

    Args:
        body (dict[str, Any]): Responses API JSON payload.

    Returns:
        str: Concatenated assistant output text (``""`` when none present).

    Raises:
        ValueError: When the body carries no ``output`` array.

    Examples:
        >>> _assistant_text_from_responses(
        ...     {
        ...         "output": [
        ...             {
        ...                 "type": "message",
        ...                 "content": [{"type": "output_text", "text": "ok"}],
        ...             }
        ...         ]
        ...     }
        ... )
        'ok'
    """
    output = body.get("output")
    if not isinstance(output, list) or not output:
        msg = "Responses body missing output messages"
        raise ValueError(msg)
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in ("output_text", "text"):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
    return "".join(parts)


def _tool_calls_from_responses(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract OpenAI-shaped ``tool_calls`` from a Responses ``output`` array.

    Maps each Responses ``function_call`` output item
    (``{"type":"function_call","call_id"|"id","name","arguments"}``) into an OpenAI
    chat-completions tool call
    (``{"id","type":"function","function":{"name","arguments"}}``).

    Args:
        body (dict[str, Any]): Responses API JSON payload.

    Returns:
        list[dict[str, Any]]: OpenAI tool-call objects (empty when none present).

    Examples:
        >>> _tool_calls_from_responses(
        ...     {
        ...         "output": [
        ...             {
        ...                 "type": "function_call",
        ...                 "call_id": "call_1",
        ...                 "name": "get_weather",
        ...                 "arguments": "{}",
        ...             }
        ...         ]
        ...     }
        ... )
        [{'id': 'call_1', 'type': 'function', 'function': {'name': 'get_weather', 'arguments': '{}'}}]
    """
    output = body.get("output")
    if not isinstance(output, list):
        return []
    calls: list[dict[str, Any]] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "function_call":
            continue
        call_id = item.get("call_id") or item.get("id") or ""
        arguments = item.get("arguments")
        calls.append(
            {
                "id": str(call_id),
                "type": "function",
                "function": {
                    "name": str(item.get("name") or ""),
                    "arguments": arguments if isinstance(arguments, str) else "{}",
                },
            },
        )
    return calls


def translate_responses_to_chat_completion(responses_body: dict[str, Any]) -> dict[str, Any]:
    """Translate a Codex Responses JSON body to chat-completions shape.

    Args:
        responses_body (dict[str, Any]): Responses API JSON payload.

    Returns:
        dict[str, Any]: OpenAI chat completion object.

    Raises:
        ValueError: When the Responses payload cannot be mapped.
        KeyError: When required fields are absent.
        TypeError: When fields have unexpected types.

    Examples:
        >>> chat = translate_responses_to_chat_completion(
        ...     {
        ...         "id": "r1",
        ...         "output": [
        ...             {
        ...                 "type": "message",
        ...                 "role": "assistant",
        ...                 "content": [{"type": "output_text", "text": "ok"}],
        ...             }
        ...         ],
        ...     }
        ... )
        >>> chat["object"]
        'chat.completion'
    """
    if not isinstance(responses_body, dict):
        msg = "expected Responses object body"
        raise TypeError(msg)
    text = _assistant_text_from_responses(responses_body)
    tool_calls = _tool_calls_from_responses(responses_body)
    if not text and not tool_calls:
        msg = "Responses body has no assistant text or tool calls"
        raise ValueError(msg)
    resp_id = str(responses_body.get("id") or f"chatcmpl-{uuid.uuid4().hex[:12]}")
    message: dict[str, Any] = {"role": "assistant", "content": text or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": resp_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": str(responses_body.get("model") or ""),
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            },
        ],
    }


def _chat_stream_frame(*, delta: dict[str, Any], chunk_id: str, finish_reason: str | None) -> str:
    """Format one chat-completions ``chat.completion.chunk`` SSE ``data:`` line.

    Args:
        delta (dict[str, Any]): The ``choices[0].delta`` payload for this chunk.
        chunk_id (str): Stable completion id for the stream.
        finish_reason (str | None): The ``finish_reason`` for this chunk.

    Returns:
        str: One SSE ``data:`` frame ending with a blank line.

    Examples:
        >>> "tool_calls" in _chat_stream_frame(
        ...     delta={}, chunk_id="c1", finish_reason="tool_calls"
        ... )
        True
    """
    payload = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _chat_stream_chunk(*, content: str, chunk_id: str) -> str:
    """Format one chat-completions text-delta SSE ``data:`` line.

    Args:
        content (str): Delta text for the chunk.
        chunk_id (str): Stable completion id for the stream.

    Returns:
        str: One SSE ``data:`` frame ending with a blank line.

    Examples:
        >>> "data:" in _chat_stream_chunk(content="Hi", chunk_id="c1")
        True
    """
    return _chat_stream_frame(delta={"content": content}, chunk_id=chunk_id, finish_reason=None)


def translate_responses_sse_to_chat_stream(raw_sse: str) -> Iterator[str]:
    """Translate Responses SSE lines to chat-completions stream chunks.

    Args:
        raw_sse (str): Upstream ``text/event-stream`` payload.

    Returns:
        Iterator[str]: Chat-completions ``data:`` lines (including terminal ``[DONE]``).

    Function calls translate to ``choices[0].delta.tool_calls[]`` chunks: a
    ``response.output_item.added`` event carrying a ``function_call`` item opens a
    tool call (emitting ``index``/``id``/``function.name``), each
    ``response.function_call_arguments.delta`` appends to ``function.arguments``,
    and the terminal ``response.completed`` emits ``finish_reason="tool_calls"``
    when any tool call was seen (otherwise ``"stop"``).

    Args:
        raw_sse (str): Upstream ``text/event-stream`` payload.

    Returns:
        Iterator[str]: Chat-completions ``data:`` lines (including terminal ``[DONE]``).

    Examples:
        >>> chunks = list(
        ...     translate_responses_sse_to_chat_stream(
        ...         'data: {"type":"response.output_text.delta","delta":"Hi"}\\n'
        ...     )
        ... )
        >>> any("delta" in c for c in chunks)
        True
        >>> tool = list(
        ...     translate_responses_sse_to_chat_stream(
        ...         'data: {"type":"response.output_item.added","output_index":0,'
        ...         '"item":{"type":"function_call","call_id":"c1","name":"f"}}\\n'
        ...     )
        ... )
        >>> any("tool_calls" in c for c in tool)
        True
    """
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    # Map a Codex ``output_index`` / ``item_id`` to a dense chat tool_call index.
    tool_index_by_key: dict[str, int] = {}

    def _tool_index(event: dict[str, Any]) -> int:
        key = str(
            event.get("output_index")
            if event.get("output_index") is not None
            else event.get("item_id", ""),
        )
        if key not in tool_index_by_key:
            tool_index_by_key[key] = len(tool_index_by_key)
        return tool_index_by_key[key]

    normalized = raw_sse.replace("\r\n", "\n")
    for block in normalized.split("\n\n"):
        saw_done = any(
            line.startswith("data:") and line[5:].strip() == "[DONE]" for line in block.split("\n")
        )
        for event in _parse_sse_event_block(block):
            event_type = event.get("type")
            if event_type == "response.output_text.delta":
                delta = event.get("delta")
                if isinstance(delta, str) and delta:
                    yield _chat_stream_chunk(content=delta, chunk_id=chunk_id)
            elif event_type == "response.output_item.added":
                item = event.get("item")
                if isinstance(item, dict) and item.get("type") == "function_call":
                    idx = _tool_index(event)
                    tool_call: dict[str, Any] = {
                        "index": idx,
                        "id": str(item.get("call_id") or item.get("id") or ""),
                        "type": "function",
                        "function": {"name": str(item.get("name") or ""), "arguments": ""},
                    }
                    yield _chat_stream_frame(
                        delta={"tool_calls": [tool_call]},
                        chunk_id=chunk_id,
                        finish_reason=None,
                    )
            elif event_type == "response.function_call_arguments.delta":
                delta = event.get("delta")
                if isinstance(delta, str) and delta:
                    idx = _tool_index(event)
                    yield _chat_stream_frame(
                        delta={
                            "tool_calls": [
                                {"index": idx, "function": {"arguments": delta}},
                            ],
                        },
                        chunk_id=chunk_id,
                        finish_reason=None,
                    )
            elif event_type == "response.completed":
                # The terminal event carries the full Responses object; consult its
                # ``output`` for function calls so the finish_reason is correct even
                # when the open/args events arrived in earlier flushes (the route
                # buffers and resets per SSE event boundary).
                response = event.get("response")
                had_tool_call = bool(tool_index_by_key) or (
                    isinstance(response, dict) and bool(_tool_calls_from_responses(response))
                )
                finish = "tool_calls" if had_tool_call else "stop"
                yield _chat_stream_frame(delta={}, chunk_id=chunk_id, finish_reason=finish)
        if saw_done:
            yield "data: [DONE]\n\n"


def _parse_sse_event_block(block: str) -> list[dict[str, Any]]:
    """Decode the JSON event object(s) carried by one SSE event block.

    Per the SSE spec, a single event may spread its payload across multiple
    ``data:`` lines that must be concatenated (joined with ``\\n``) before being
    JSON-decoded. Real Codex Responses events — notably the large terminal
    ``response.completed`` carrying ``reasoning.encrypted_content`` — rely on this
    multi-line framing, so a line-by-line decode of each ``data:`` line fails. This
    helper collects every ``data:`` line in the block and first tries the spec form
    (join all lines, decode once). If that join does not decode (legacy / test
    streams that pack several standalone ``data:`` events into one block with no
    blank separator), it falls back to decoding each ``data:`` line on its own. The
    ``[DONE]`` sentinel and undecodable / non-object payloads are dropped.

    Args:
        block (str): One event block (the text between ``\\n\\n`` boundaries).

    Returns:
        list[dict[str, Any]]: Decoded event objects from this block (empty for a
        comment, blank, ``[DONE]`` sentinel, or undecodable / non-object payload).

    Examples:
        >>> _parse_sse_event_block('data: {"type":"response.completed"}')
        [{'type': 'response.completed'}]
        >>> _parse_sse_event_block('data: {"a":1,\\ndata:  "b":2}')
        [{'a': 1, 'b': 2}]
        >>> _parse_sse_event_block('data: {"x":1}\\ndata: {"y":2}')
        [{'x': 1}, {'y': 2}]
        >>> _parse_sse_event_block('data: [DONE]')
        []
    """
    data_lines = [line[5:].lstrip(" ") for line in block.split("\n") if line.startswith("data:")]
    if not data_lines:
        return []
    joined = "\n".join(data_lines).strip()
    if not joined or joined == "[DONE]":
        return []
    try:
        event = json.loads(joined)
    except json.JSONDecodeError:
        pass
    else:
        return [event] if isinstance(event, dict) else []
    # Fallback: the block is several standalone ``data:`` events (no blank line
    # between them) rather than one multi-line ``data:`` field. Decode per line.
    events: list[dict[str, Any]] = []
    for line in data_lines:
        candidate = line.strip()
        if not candidate or candidate == "[DONE]":
            continue
        try:
            decoded = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            events.append(decoded)
    return events


def _iter_sse_events(raw_sse: str) -> Iterator[dict[str, Any]]:
    """Yield decoded JSON event objects from a Responses ``text/event-stream`` payload.

    Splits the raw stream into events on ``\\n\\n`` block boundaries (tolerating a
    trailing event with no terminal blank line), then decodes each block via
    :func:`_parse_sse_event_block`. This honours SSE multi-line ``data:`` framing
    where one event's JSON spans several ``data:`` lines, while still tolerating
    legacy ``\\n``-separated standalone events. Skips comment blocks, blank blocks,
    the terminal ``[DONE]`` sentinel, and any payload that is not a JSON object.

    Args:
        raw_sse (str): Raw upstream SSE text (one or more events).

    Returns:
        Iterator[dict[str, Any]]: Decoded event objects in arrival order.

    Examples:
        >>> events = list(
        ...     _iter_sse_events('data: {"type":"response.completed"}\\n\\ndata: [DONE]')
        ... )
        >>> events == [{"type": "response.completed"}]
        True
        >>> list(_iter_sse_events('data: {"x":1,\\ndata:  "y":2}\\n\\n'))
        [{'x': 1, 'y': 2}]
    """
    normalized = raw_sse.replace("\r\n", "\n")
    for block in normalized.split("\n\n"):
        yield from _parse_sse_event_block(block)


def _reconstruct_output_items(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rebuild the Responses ``output[]`` list from streamed output-item events.

    Codex delivers each completed output object (``message`` / ``function_call`` /
    ``reasoning``) via a ``response.output_item.done`` event carrying the finished
    ``item``. The terminal ``response.completed`` event's ``response.output`` is an
    **empty list** — it does not re-include the items — so the non-streaming caller
    must reconstruct ``output[]`` from these per-item events instead.

    Items are collected in arrival order. A ``response.output_item.added`` seeds the
    slot for its ``output_index`` (fallback: ``item.id``) so partial streams still
    surface an item, and a later ``response.output_item.done`` for the same slot
    supersedes it with the completed object.

    Args:
        events (list[dict[str, Any]]): Decoded Responses SSE events in arrival order.

    Returns:
        list[dict[str, Any]]: Reconstructed output items in arrival order (empty
        when the stream carried no output-item events).

    Examples:
        >>> _reconstruct_output_items(
        ...     [
        ...         {
        ...             "type": "response.output_item.done",
        ...             "output_index": 0,
        ...             "item": {
        ...                 "type": "message",
        ...                 "content": [{"type": "output_text", "text": "hi"}],
        ...             },
        ...         }
        ...     ]
        ... )
        [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'hi'}]}]
    """
    order: list[str] = []
    items_by_key: dict[str, dict[str, Any]] = {}
    done_keys: set[str] = set()

    def _key(event: dict[str, Any], item: dict[str, Any] | None) -> str:
        idx = event.get("output_index")
        if idx is not None:
            return str(idx)
        item_id = event.get("item_id") or (item.get("id") if isinstance(item, dict) else None)
        return str(item_id) if item_id is not None else str(len(order))

    for event in events:
        event_type = event.get("type")
        if event_type in ("response.output_item.added", "response.output_item.done"):
            item = event.get("item")
            if not isinstance(item, dict):
                continue
            key = _key(event, item)
            if key not in items_by_key:
                order.append(key)
            # ``.done`` is authoritative and supersedes any earlier ``.added``;
            # a fresh ``.added`` only seeds a slot that has no item yet.
            if event_type == "response.output_item.done":
                items_by_key[key] = item
                done_keys.add(key)
            elif key not in items_by_key:
                items_by_key[key] = dict(item)
        elif event_type == "response.function_call_arguments.delta":
            # Streamed function-call arguments accumulate onto the seeded item until
            # the authoritative ``.done`` (if any) replaces it wholesale.
            delta = event.get("delta")
            if not isinstance(delta, str) or not delta:
                continue
            key = _key(event, None)
            slot = items_by_key.get(key)
            if isinstance(slot, dict) and key not in done_keys:
                existing = slot.get("arguments")
                slot["arguments"] = (existing if isinstance(existing, str) else "") + delta
    return [items_by_key[key] for key in order]


def aggregate_responses_sse(raw_sse: str) -> dict[str, Any]:
    """Assemble the terminal Responses object from a Codex Responses SSE stream.

    Codex (``backend-api/codex/responses``) only supports streaming, so the
    non-streaming caller path must buffer the whole SSE stream and reconstruct the
    final Responses object. The stream is split into events on ``\\n\\n`` block
    boundaries and each block's (possibly multi-line) ``data:`` payload is joined
    before decoding (see :func:`_parse_sse_event_block`).

    Critically, Codex sends the terminal ``response.completed`` event with an
    **empty** ``response.output`` list — it does *not* re-include the assistant
    content there. The real output objects (``message`` / ``function_call`` /
    ``reasoning``) arrive via ``response.output_item.done`` events, each carrying a
    completed ``item``. This helper therefore reconstructs ``output[]`` from those
    per-item events (see :func:`_reconstruct_output_items`) and uses the terminal
    ``response.completed.response`` object purely as the envelope (id, model,
    usage, …) with its ``output`` replaced by the reconstructed list.

    Fallbacks, in order: (1) reconstructed items over the terminal envelope; (2) a
    terminal ``response`` dict whose own ``output`` is already populated (legacy /
    non-Codex upstreams that do re-include output); (3) the most recent event with
    a ``response`` dict; (4) concatenated ``response.output_text.delta`` deltas as a
    single assistant message so a partial stream still yields usable text.

    Args:
        raw_sse (str): Raw upstream ``text/event-stream`` payload (UTF-8 decoded).

    Returns:
        dict[str, Any]: Terminal Responses object suitable for
        :func:`translate_responses_to_chat_completion`.

    Raises:
        ValueError: When the stream carries no output items, no terminal Responses
            object, and no assistant text deltas.

    Examples:
        >>> body = aggregate_responses_sse(
        ...     'data: {"type":"response.output_item.done","output_index":0,"item":'
        ...     '{"type":"message","content":'
        ...     '[{"type":"output_text","text":"ok"}]}}\\n\\n'
        ...     'data: {"type":"response.completed","response":'
        ...     '{"id":"r1","output":[]}}\\n'
        ... )
        >>> body["id"], body["output"][0]["content"][0]["text"]
        ('r1', 'ok')
        >>> aggregate_responses_sse(
        ...     'data: {"type":"response.output_text.delta","delta":"Hi"}\\n'
        ...     'data: {"type":"response.output_text.delta","delta":" there"}\\n'
        ... )["output"][0]["content"][0]["text"]
        'Hi there'
    """
    events = list(_iter_sse_events(raw_sse))
    reconstructed = _reconstruct_output_items(events)

    envelope: dict[str, Any] | None = None
    for event in reversed(events):
        response = event.get("response")
        if event.get("type") == "response.completed" and isinstance(response, dict):
            envelope = response
            break

    if reconstructed:
        # Codex path: the terminal envelope's ``output`` is empty; splice in the
        # items reconstructed from the ``output_item.done`` stream.
        base = dict(envelope) if envelope is not None else {}
        base["output"] = reconstructed
        return base

    # No per-item events. Prefer a terminal envelope that already carries output.
    if envelope is not None:
        return envelope

    # Broader fallback: the most recent event whose ``response`` is a dict, even
    # without a terminal ``response.completed`` type (e.g. a late
    # ``response.incomplete`` snapshot still carries usable content).
    for event in reversed(events):
        response = event.get("response")
        if isinstance(response, dict):
            return response

    output_text = "".join(
        delta
        for event in events
        if event.get("type") == "response.output_text.delta"
        and isinstance((delta := event.get("delta")), str)
    )
    if output_text:
        return {
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": output_text}],
                },
            ],
        }
    msg = "Responses SSE stream carried no terminal object or assistant text"
    raise ValueError(msg)


__all__ = [
    "CODEX_DEFAULT_INSTRUCTIONS",
    "aggregate_responses_sse",
    "translate_chat_to_responses_request",
    "translate_responses_sse_to_chat_stream",
    "translate_responses_to_chat_completion",
]
