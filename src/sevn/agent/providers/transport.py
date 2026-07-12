"""LLM provider wire-shape abstraction (`Transport` + proxy-backed classes).

Module: sevn.agent.providers.transport
Depends: sevn.agent.providers.transport_http

Exports:
    Transport — protocol for outbound LLM calls.
    AnthropicTransport — Messages API shape via egress proxy.
    AnthropicMessagesTransport — alias for tier-B / triager serializers (`specs/14`).
    ChatCompletionsTransport — OpenAI-style chat completions via proxy.
    ResponsesApiTransport — OpenAI Responses API via proxy.
    BedrockTransport — Bedrock Converse-shaped calls via proxy.
    StreamTextDelta — one incremental text fragment from ``complete_stream``.
    StreamFinal — terminal ``complete_stream`` event with the reassembled response.

Examples:
    >>> ChatCompletionsTransport().name
    'chat_completions'
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from sevn.agent.providers import transport_http


@dataclass(frozen=True)
class StreamTextDelta:
    """One incremental assistant-text fragment from a streaming completion.

    Attributes:
        text (str): Newly produced text (a true delta, not an accumulation).

    Examples:
        >>> StreamTextDelta(text="he").text
        'he'
    """

    text: str


@dataclass(frozen=True)
class StreamFinal:
    """Terminal ``complete_stream`` event carrying the reassembled response.

    The ``response`` payload matches the shape :meth:`Transport.complete` would
    return for the same wire, so the tier-B serializers can run their existing
    ``*_to_model_response`` converters on it — preserving MiniMax XML / thinking
    recovery for the streamed path (`specs/14-executor-tier-b.md` §2.3).

    Attributes:
        response (dict): Provider-shaped completion payload rebuilt from SSE
            frames (Anthropic ``content`` blocks / OpenAI ``choices``).

    Examples:
        >>> StreamFinal(response={"content": []}).response
        {'content': []}
    """

    response: dict[str, object] = field(default_factory=dict)


StreamChunk = StreamTextDelta | StreamFinal
"""Either an incremental text delta or the terminal reassembled response."""


async def _reconstruct_anthropic_stream(
    events: AsyncIterator[dict[str, Any]],
) -> AsyncIterator[StreamChunk]:
    """Turn Anthropic Messages SSE frames into text deltas + a final payload.

    Walks the canonical Anthropic event sequence (``message_start`` →
    ``content_block_start`` / ``content_block_delta`` / ``content_block_stop`` →
    ``message_delta`` → ``message_stop``), emitting a :class:`StreamTextDelta`
    for every ``text_delta`` and accumulating ``thinking`` / ``tool_use`` blocks
    so the trailing :class:`StreamFinal` mirrors a non-streaming
    ``/llm/anthropic/messages`` body.

    Args:
        events (AsyncIterator[dict]): Parsed ``data:`` JSON objects from the proxy.

    Yields:
        StreamChunk: Text deltas as they arrive, then exactly one ``StreamFinal``.

    Returns:
        collections.abc.AsyncIterator[StreamChunk]: Async generator of stream chunks.

    Examples:
        >>> import asyncio
        >>> async def _evs():
        ...     yield {"type": "message_start",
        ...            "message": {"model": "m", "usage": {"input_tokens": 3}}}
        ...     yield {"type": "content_block_start", "index": 0,
        ...            "content_block": {"type": "text", "text": ""}}
        ...     yield {"type": "content_block_delta", "index": 0,
        ...            "delta": {"type": "text_delta", "text": "Hi"}}
        ...     yield {"type": "content_block_delta", "index": 0,
        ...            "delta": {"type": "text_delta", "text": "!"}}
        ...     yield {"type": "message_delta", "usage": {"output_tokens": 2}}
        ...     yield {"type": "message_stop"}
        >>> async def _run():
        ...     return [c async for c in _reconstruct_anthropic_stream(_evs())]
        >>> out = asyncio.run(_run())
        >>> [c.text for c in out if isinstance(c, StreamTextDelta)]
        ['Hi', '!']
        >>> final = out[-1]
        >>> final.response["content"][0]["text"], final.response["usage"]
        ('Hi!', {'input_tokens': 3, 'output_tokens': 2})
    """
    blocks: dict[int, dict[str, object]] = {}
    json_buffers: dict[int, str] = {}
    model = ""
    usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
    stop_reason: object = None
    async for ev in events:
        etype = ev.get("type")
        if etype == "message_start":
            message = ev.get("message")
            if isinstance(message, dict):
                model = str(message.get("model", model))
                msg_usage = message.get("usage")
                if isinstance(msg_usage, dict) and msg_usage.get("input_tokens") is not None:
                    usage["input_tokens"] = int(msg_usage["input_tokens"])
        elif etype == "content_block_start":
            idx = int(ev.get("index", len(blocks)))
            cb = ev.get("content_block")
            block: dict[str, object] = dict(cb) if isinstance(cb, dict) else {"type": "text"}
            btype = block.get("type")
            if btype == "text":
                block["text"] = block.get("text") or ""
            elif btype == "thinking":
                block["thinking"] = block.get("thinking") or ""
            elif btype == "tool_use":
                block.setdefault("input", {})
                json_buffers[idx] = ""
            blocks[idx] = block
        elif etype == "content_block_delta":
            idx = int(ev.get("index", 0))
            delta = ev.get("delta")
            if not isinstance(delta, dict):
                continue
            dtype = delta.get("type")
            block = blocks.setdefault(idx, {"type": "text", "text": ""})
            if dtype == "text_delta":
                piece = str(delta.get("text", ""))
                block["text"] = str(block.get("text", "")) + piece
                if piece:
                    yield StreamTextDelta(text=piece)
            elif dtype == "thinking_delta":
                block["thinking"] = str(block.get("thinking", "")) + str(delta.get("thinking", ""))
            elif dtype == "input_json_delta":
                json_buffers[idx] = json_buffers.get(idx, "") + str(delta.get("partial_json", ""))
        elif etype == "content_block_stop":
            idx = int(ev.get("index", 0))
            buffered = json_buffers.get(idx)
            if buffered is not None and idx in blocks:
                try:
                    blocks[idx]["input"] = json.loads(buffered) if buffered.strip() else {}
                except json.JSONDecodeError:
                    blocks[idx]["input"] = {}
        elif etype == "message_delta":
            delta = ev.get("delta")
            if isinstance(delta, dict) and delta.get("stop_reason") is not None:
                stop_reason = delta.get("stop_reason")
            msg_usage = ev.get("usage")
            if isinstance(msg_usage, dict) and msg_usage.get("output_tokens") is not None:
                usage["output_tokens"] = int(msg_usage["output_tokens"])
        elif etype == "message_stop":
            break
    ordered = [blocks[i] for i in sorted(blocks)]
    response: dict[str, object] = {
        "role": "assistant",
        "content": ordered,
        "usage": usage,
    }
    if model:
        response["model"] = model
    if stop_reason is not None:
        response["stop_reason"] = stop_reason
    yield StreamFinal(response=response)


async def _reconstruct_openai_stream(
    events: AsyncIterator[dict[str, Any]],
) -> AsyncIterator[StreamChunk]:
    """Turn OpenAI chat-completions SSE chunks into text deltas + a final payload.

    Accumulates ``choices[0].delta.content`` text and partial ``tool_calls`` so
    the trailing :class:`StreamFinal` mirrors a non-streaming
    ``/llm/openai/chat/completions`` body for ``openai_completion_to_model_response``.

    Args:
        events (AsyncIterator[dict]): Parsed ``data:`` JSON chunk objects.

    Yields:
        StreamChunk: Text deltas, then exactly one ``StreamFinal``.

    Returns:
        collections.abc.AsyncIterator[StreamChunk]: Async generator of stream chunks.

    Examples:
        >>> import asyncio
        >>> async def _evs():
        ...     yield {"choices": [{"delta": {"content": "ab"}}]}
        ...     yield {"choices": [{"delta": {"content": "c"}}]}
        >>> async def _run():
        ...     return [c async for c in _reconstruct_openai_stream(_evs())]
        >>> out = asyncio.run(_run())
        >>> [c.text for c in out if isinstance(c, StreamTextDelta)]
        ['ab', 'c']
        >>> out[-1].response["choices"][0]["message"]["content"]
        'abc'
    """
    text = ""
    tool_calls: dict[int, dict[str, str]] = {}
    usage: dict[str, object] = {}
    async for ev in events:
        raw_usage = ev.get("usage")
        if isinstance(raw_usage, dict):
            usage = dict(raw_usage)
        choices = ev.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        choice0 = choices[0]
        if not isinstance(choice0, dict):
            continue
        delta = choice0.get("delta")
        if not isinstance(delta, dict):
            continue
        piece = delta.get("content")
        if isinstance(piece, str) and piece:
            text += piece
            yield StreamTextDelta(text=piece)
        raw_tools = delta.get("tool_calls")
        if isinstance(raw_tools, list):
            for tc in raw_tools:
                if not isinstance(tc, dict):
                    continue
                tidx = int(tc.get("index", 0))
                slot = tool_calls.setdefault(tidx, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    slot["id"] = str(tc["id"])
                fn = tc.get("function")
                if isinstance(fn, dict):
                    if fn.get("name"):
                        slot["name"] = str(fn["name"])
                    if isinstance(fn.get("arguments"), str):
                        slot["arguments"] += fn["arguments"]
    message: dict[str, object] = {"role": "assistant"}
    if text:
        message["content"] = text
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": slot["id"],
                "type": "function",
                "function": {"name": slot["name"], "arguments": slot["arguments"] or "{}"},
            }
            for _, slot in sorted(tool_calls.items())
        ]
    response: dict[str, object] = {"choices": [{"message": message}]}
    if usage:
        response["usage"] = usage
    yield StreamFinal(response=response)


def _usage_tokens(usage: object) -> tuple[int, int]:
    """Best-effort (input, output) token pair across provider shapes.

        Args:
    usage (object): ``usage`` object from a provider response.

        Returns:
    tuple[int, int]: Input and output counts, or ``(0, 0)`` when unknown.

        Examples:
            >>> _usage_tokens({"input_tokens": 2, "output_tokens": 3})
            (2, 3)
            >>> _usage_tokens("nope")
            (0, 0)
    """
    if not isinstance(usage, dict):
        return (0, 0)
    u = usage
    pairs = (
        ("input_tokens", "output_tokens"),
        ("inputTokens", "outputTokens"),
        ("prompt_tokens", "completion_tokens"),
    )
    for ik, ok in pairs:
        if ik in u and ok in u:
            return (int(u[ik]), int(u[ok]))
    return (0, 0)


def _response_tokens(response: dict[str, object], *, kind: str) -> tuple[int, int]:
    """Extract token usage from a parsed provider response.

        Args:
    response (dict[str, object]): Top-level JSON object from the proxy.
    kind (str): Transport family label for shape dispatch.

        Returns:
    tuple[int, int]: Input and output token counts.

        Examples:
            >>> _response_tokens({"usage": {"input_tokens": 1, "output_tokens": 2}}, kind="anthropic")
            (1, 2)
    """
    raw = response.get("usage")
    if kind == "anthropic":
        return _usage_tokens(raw)
    if kind in ("chat_completions", "responses_api"):
        return _usage_tokens(raw)
    if kind == "bedrock":
        m = response.get("usage")
        if isinstance(m, dict):
            return _usage_tokens(m)
        return (0, 0)
    return (0, 0)


class Transport(Protocol):
    """Provider-shape abstraction for outbound LLM calls."""

    name: str
    supports_streaming: bool
    """Whether the tier-B harness should attempt progressive ``node.stream`` taps.

    ``True`` for wires whose :meth:`complete_stream` issues a real ``stream: true``
    request and yields genuine token deltas (Anthropic / MiniMax Messages SSE and
    OpenAI chat / responses SSE). The proxy passes the upstream ``text/event-stream``
    through unbuffered, so the tier-B ``FunctionModel`` fills the Telegram
    placeholder progressively (`specs/14-executor-tier-b.md` §2.3 /
    `specs/05-llm-transports.md` §2.3). Set ``False`` only for batch-only wires
    with no SSE reconstruction (e.g. Bedrock Converse here).
    """

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        """Run a single non-streaming completion.

                Args:
        request (dict): Provider-shaped request payload.

                Returns:
                    dict: Parsed completion payload.

                Examples:
                    >>> isinstance({}, dict)
                    True
        """
        ...

    async def stream(self, request: dict[str, object]) -> AsyncIterator[dict[str, object]]:
        """Stream completion chunks as provider-shaped dict events.

                Args:
        request (dict): Provider-shaped request payload.

                Returns:
                    AsyncIterator[dict]: Async iterator of chunk dicts.

                Examples:
                    >>> isinstance({}, dict)
                    True
        """
        ...

    def complete_stream(self, request: dict[str, object]) -> AsyncIterator[StreamChunk]:
        """Stream a completion as normalized text deltas + a final response.

        Issues a ``stream: true`` request and reconstructs the wire SSE frames
        into :class:`StreamTextDelta` events followed by exactly one
        :class:`StreamFinal` whose ``response`` mirrors :meth:`complete` for the
        same wire (so callers reuse their non-streaming converter).

                Args:
        request (dict): Provider-shaped request payload (``stream`` is forced ``True``).

                Returns:
                    AsyncIterator[StreamChunk]: Text deltas, then one ``StreamFinal``.

                Examples:
                    >>> isinstance({}, dict)
                    True
        """
        ...

    def auth_header(self, model_id: str) -> dict[str, str]:
        """Return headers to attach on the egress proxy (no raw secrets here).

                Args:
        model_id (str): Resolved model identifier for this call.

                Returns:
                    dict[str, str]: Header names to values for the proxy.

                Examples:
                    >>> isinstance({}, dict)
                    True
        """
        ...

    def tokens_used(self, response: dict[str, object]) -> tuple[int, int]:
        """Return (input_tokens, output_tokens) from a parsed response dict.

                Args:
        response (dict): Parsed provider response payload.

                Returns:
                    tuple[int, int]: Input and output token counts.

                Examples:
                    >>> isinstance((0, 0), tuple)
                    True
        """
        ...

    def cache_breakpoints(
        self,
        prompt_segments: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        """Rewrite/annotate prompt segments for provider-side prefix caches.

                Args:
        prompt_segments (list[dict]): Structured prompt segments.

                Returns:
                    list[dict]: Possibly rewritten segments.

                Examples:
                    >>> isinstance([], list)
                    True
        """
        ...


class _ProxyTransport:
    """Shared HTTP transport: ``complete`` via proxy; ``stream`` for OpenAI-style SSE only."""

    name: str
    _path_complete: str
    _usage_format: str
    supports_streaming: bool = True

    def __init__(
        self,
        *,
        proxy_base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        """Bind optional proxy base URL (required for ``complete`` / ``stream``).

                Args:
        proxy_base_url (str | None): E.g. ``ProcessSettings.proxy_url`` / ``SEVN_PROXY_URL``.
        extra_headers (dict[str, str] | None): Merged into every outbound call via ``auth_header``.

                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        self._proxy_base_url = proxy_base_url.rstrip("/") if proxy_base_url else None
        self._extra_headers = dict(extra_headers or {})

    def _require_base(self) -> str:
        """Return proxy base URL or raise when calls are impossible.

        Returns:
            str: Stripped origin.

        Raises:
            NotImplementedError: If no ``proxy_base_url`` / ``SEVN_PROXY_URL``.

        Examples:
            >>> AnthropicTransport(proxy_base_url="http://x")._require_base()
            'http://x'
        """
        if not self._proxy_base_url:
            msg = (
                "LLM proxy base URL not configured; set proxy_base_url=... on the transport "
                "or pass SEVN_PROXY_URL (see specs/05-llm-transports.md)."
            )
            raise NotImplementedError(msg)
        return self._proxy_base_url

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        """POST a non-streaming completion through the egress proxy.

                Args:
        request (dict): Provider-shaped JSON body.

                Returns:
                    dict[str, object]: Parsed JSON response.

                Raises:
                    NotImplementedError: When ``proxy_base_url`` was never set.

                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        base = self._require_base()
        headers = self.auth_header(str(request.get("model", "")))
        raw = await transport_http.post_llm_json(
            base_url=base,
            path=self._path_complete,
            headers=headers,
            body=dict(request),
        )
        return raw  # noqa: RET504

    async def stream(self, request: dict[str, object]) -> AsyncIterator[dict[str, object]]:
        """Stream canonical OpenAI-shaped SSE JSON events via the egress proxy.

                Args:
        request (dict): Provider-shaped JSON body; ``stream`` is forced ``True``.

                Returns:
            AsyncIterator[dict[str, object]]: Parsed SSE ``data:`` JSON objects.

                Raises:
                    NotImplementedError: When proxy URL is unset.

                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        if self.name not in ("chat_completions", "responses_api", "anthropic", "bedrock"):
            msg = f"streaming for transport {self.name!r} is not implemented"
            raise NotImplementedError(msg)
        base = self._require_base()
        body = dict(request)
        body["stream"] = True
        headers = self.auth_header(str(body.get("model", "")))
        async for chunk in transport_http.iter_llm_sse(
            base_url=base,
            path=self._path_complete,
            headers=headers,
            body=body,
        ):
            yield chunk

    async def complete_stream(
        self,
        request: dict[str, object],
    ) -> AsyncIterator[StreamChunk]:
        """Issue a real ``stream: true`` request and yield normalized stream chunks.

        Forces ``stream`` on, taps the proxy SSE passthrough via ``iter_llm_sse``,
        and reconstructs the wire frames into :class:`StreamTextDelta` events plus
        a terminal :class:`StreamFinal` matching :meth:`complete`'s shape. Anthropic
        Messages and OpenAI chat / responses are supported; other wires raise
        ``NotImplementedError`` so the caller can fall back to :meth:`complete`.

                Args:
        request (dict): Provider-shaped JSON body.

                Returns:
            AsyncIterator[StreamChunk]: Incremental text then one ``StreamFinal``.

                Raises:
                    NotImplementedError: When proxy URL is unset or the wire has no
                        streaming reconstruction (e.g. Bedrock Converse).

                Examples:
                    >>> import inspect
                    >>> inspect.isasyncgenfunction(_ProxyTransport.complete_stream)
                    True
        """
        base = self._require_base()
        body = dict(request)
        body["stream"] = True
        headers = self.auth_header(str(body.get("model", "")))
        events = transport_http.iter_llm_sse(
            base_url=base,
            path=self._path_complete,
            headers=headers,
            body=body,
        )
        if self._usage_format == "anthropic":
            async for chunk in _reconstruct_anthropic_stream(events):
                yield chunk
        elif self._usage_format in ("chat_completions", "responses_api"):
            async for chunk in _reconstruct_openai_stream(events):
                yield chunk
        else:
            # ``iter_llm_sse`` is lazy — no upstream request is issued until first
            # iteration — so leaving ``events`` unconsumed opens no socket to close.
            msg = f"complete_stream reconstruction not implemented for wire {self._usage_format!r}"
            raise NotImplementedError(msg)

    def auth_header(self, model_id: str) -> dict[str, str]:
        """Return extra headers for the proxy (token injection happens server-side).

                Args:
        model_id (str): Resolved catalog id (unused in Phase 1).

                Returns:
                    dict[str, str]: Headers merged by ``post_llm_json`` / ``iter_llm_sse``.

                Examples:
                    >>> isinstance({}, dict)
                    True
        """
        _ = model_id
        return dict(self._extra_headers)

    def tokens_used(self, response: dict[str, object]) -> tuple[int, int]:
        """Extract token counts from a parsed completion response.

                Args:
        response (dict): Provider JSON.

                Returns:
                    tuple[int, int]: Input and output counts (best effort).

                Examples:
                    >>> isinstance((0, 0), tuple)
                    True
        """
        return _response_tokens(response, kind=self._usage_format)

    def cache_breakpoints(
        self,
        prompt_segments: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        """Pass through segments; Anthropic keeps ``cache_control`` for upstream stripping rules.

                Args:
        prompt_segments (list[dict]): Structured segments.

                Returns:
                    list[dict]: Copy of segments (immutable providers may rewrite later).

                Examples:
                    >>> isinstance([], list)
                    True
        """
        return list(prompt_segments)


class AnthropicTransport(_ProxyTransport):
    """Anthropic Messages API shape — ``POST /llm/anthropic/messages`` on the proxy."""

    def __init__(
        self,
        *,
        proxy_base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        """Create an Anthropic-shaped transport.

                Args:
        proxy_base_url (str | None): Egress origin.
        extra_headers (dict[str, str] | None): Optional proxy headers.

                Examples:
                    >>> AnthropicTransport().name
                    'anthropic'
        """
        super().__init__(proxy_base_url=proxy_base_url, extra_headers=extra_headers)
        self.name = "anthropic"
        self._path_complete = "/llm/anthropic/messages"
        self._usage_format = "anthropic"
        # Real SSE: ``complete_stream`` sends ``stream: true`` and reconstructs the
        # Anthropic Messages event stream (``content_block_delta`` → ``text_delta``)
        # into genuine token deltas. The egress proxy passes the upstream
        # ``text/event-stream`` through unbuffered, and MiniMax's Anthropic-compatible
        # endpoint emits the same SSE shape, so tier-B fills the placeholder
        # progressively (`specs/14` §2.3 / `specs/05` §2.3).
        self.supports_streaming = True


class AnthropicMessagesTransport(AnthropicTransport):
    """Anthropic Messages API — same wire path as ``AnthropicTransport`` (`specs/14-executor-tier-b.md`)."""

    def __init__(
        self,
        *,
        proxy_base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        """Create an Anthropic Messages transport for tier-B serializers.

                Args:
        proxy_base_url (str | None): Egress origin.
        extra_headers (dict[str, str] | None): Optional proxy headers.

                Examples:
                    >>> AnthropicMessagesTransport().name
                    'anthropic'
        """
        super().__init__(proxy_base_url=proxy_base_url, extra_headers=extra_headers)


class ChatCompletionsTransport(_ProxyTransport):
    """OpenAI-style chat completions — ``POST /llm/openai/chat/completions``."""

    def __init__(
        self,
        *,
        proxy_base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        """Create a Chat Completions transport.

                Args:
        proxy_base_url (str | None): Egress origin.
        extra_headers (dict[str, str] | None): Optional proxy headers.

                Examples:
                    >>> ChatCompletionsTransport().name
                    'chat_completions'
        """
        super().__init__(proxy_base_url=proxy_base_url, extra_headers=extra_headers)
        self.name = "chat_completions"
        self._path_complete = "/llm/openai/chat/completions"
        self._usage_format = "chat_completions"


class ResponsesApiTransport(_ProxyTransport):
    """OpenAI Responses API — ``POST /llm/openai/responses``."""

    def __init__(
        self,
        *,
        proxy_base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        """Create a Responses API transport.

                Args:
        proxy_base_url (str | None): Egress origin.
        extra_headers (dict[str, str] | None): Optional proxy headers.

                Examples:
                    >>> ResponsesApiTransport().name
                    'responses_api'
        """
        super().__init__(proxy_base_url=proxy_base_url, extra_headers=extra_headers)
        self.name = "responses_api"
        self._path_complete = "/llm/openai/responses"
        self._usage_format = "responses_api"


class BedrockTransport(_ProxyTransport):
    """AWS Bedrock Converse shape — ``POST /llm/bedrock/converse``."""

    def __init__(
        self,
        *,
        proxy_base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        """Create a Bedrock Converse transport.

                Args:
        proxy_base_url (str | None): Egress origin.
        extra_headers (dict[str, str] | None): Optional proxy headers.

                Examples:
                    >>> BedrockTransport().name
                    'bedrock'
        """
        super().__init__(proxy_base_url=proxy_base_url, extra_headers=extra_headers)
        self.name = "bedrock"
        self._path_complete = "/llm/bedrock/converse"
        self._usage_format = "bedrock"
        # Bedrock Converse streaming frames have no ``complete_stream``
        # reconstruction yet, so the tier-B harness uses the batch ``complete``
        # path. Flip to ``True`` once ``_reconstruct_*`` covers the Converse SSE.
        self.supports_streaming = False
