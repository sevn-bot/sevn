"""W2 egress httpx bridge — redaction parity gate for native pydantic-ai models."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest

from sevn.agent.adapters.egress_bridge import (
    PROXY_TOKEN_HEADER,
    EgressBridgeContext,
    build_sevn_anthropic_client,
    build_sevn_httpx_event_hooks,
    build_sevn_openai_client,
    redact_httpx_request_snapshot,
    redact_llm_request_snapshot,
    redact_proxy_transport_request,
    resolve_proxy_shared_secret,
)
from sevn.agent.providers.transport import AnthropicTransport, ChatCompletionsTransport
from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy
from sevn.agent.tracing.sink import TraceEvent  # noqa: TC001 — runtime type for captured events


class _CapturingTraceSink:
    """Minimal ``TraceSink`` that records emitted events."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return

    async def close(self) -> None:
        return


_SECRET_BODY: dict[str, Any] = {
    "model": "minimax/MiniMax-M3",
    "max_tokens": 256,
    "system": "secret system prompt",
    "messages": [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "secret user prompt"},
                {"type": "tool_result", "tool_use_id": "t1", "content": "secret tool output"},
            ],
        },
    ],
    "tools": [{"name": "read", "description": "read files"}],
}

_SECRET_HEADERS: dict[str, str] = {
    "x-api-key": "sk-abcdefghijklmnopqrstuvwxyz123456",
    "authorization": "Bearer upstream-token-value",
    PROXY_TOKEN_HEADER: "proxy-shared-secret",
    "content-type": "application/json",
}


def test_resolve_proxy_shared_secret_reads_env() -> None:
    assert resolve_proxy_shared_secret(env={"SEVN_PROXY_SHARED_SECRET": " tok "}) == "tok"
    assert resolve_proxy_shared_secret(env={}) is None


def test_redaction_parity_matches_proxy_transport_anthropic() -> None:
    transport = AnthropicTransport(
        proxy_base_url="http://proxy.test",
        extra_headers={PROXY_TOKEN_HEADER: "proxy-shared-secret"},
    )
    model_id = str(_SECRET_BODY["model"])
    wire_headers = transport.auth_header(model_id)
    policy = TraceRedactionPolicy.from_defaults()
    reference = redact_proxy_transport_request(
        transport,
        model_id=model_id,
        body=_SECRET_BODY,
        redaction_policy=policy,
    )
    bridge = redact_llm_request_snapshot(
        headers=wire_headers,
        body=_SECRET_BODY,
        redaction_policy=policy,
    )
    assert json.dumps(reference, sort_keys=True) == json.dumps(bridge, sort_keys=True)


def test_redaction_parity_matches_proxy_transport_chat_completions() -> None:
    transport = ChatCompletionsTransport(
        proxy_base_url="http://proxy.test",
        extra_headers={PROXY_TOKEN_HEADER: "proxy-shared-secret"},
    )
    model_id = "openai/gpt-5-mini"
    wire_headers = transport.auth_header(model_id)
    policy = TraceRedactionPolicy.from_defaults()
    reference = redact_proxy_transport_request(
        transport,
        model_id=model_id,
        body=_SECRET_BODY,
        redaction_policy=policy,
    )
    bridge = redact_llm_request_snapshot(
        headers=wire_headers,
        body=_SECRET_BODY,
        redaction_policy=policy,
    )
    assert json.dumps(reference, sort_keys=True) == json.dumps(bridge, sort_keys=True)


@pytest.mark.asyncio
async def test_event_hooks_inject_proxy_token_and_emit_checkpoints() -> None:
    sink = _CapturingTraceSink()
    ctx = EgressBridgeContext(
        trace=sink,
        session_id="sess-1",
        turn_id="turn-1",
        tier="B",
        parent_span_id="parent-span",
        redaction_policy=TraceRedactionPolicy.from_defaults(),
    )
    hooks = build_sevn_httpx_event_hooks(ctx=ctx, shared_secret="proxy-shared-secret")

    captured: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={"id": "msg-1", "content": [{"type": "text", "text": "ok"}]},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://proxy.test",
        event_hooks=hooks,
    ) as client:
        response = await client.post(
            "/llm/anthropic/messages",
            headers=_SECRET_HEADERS,
            json=_SECRET_BODY,
        )
    assert response.status_code == 200
    header_token = captured["headers"].get(PROXY_TOKEN_HEADER) or captured["headers"].get(
        PROXY_TOKEN_HEADER.lower(),
    )
    assert header_token == "proxy-shared-secret"

    kinds = [event.kind for event in sink.events]
    assert kinds == ["provider.before", "provider.after", "provider.call"]

    before = sink.events[0]
    after = sink.events[1]
    provider_call = sink.events[2]
    assert before.span_id == after.span_id
    assert before.parent_span_id == "parent-span"
    assert before.session_id == "sess-1"
    assert before.turn_id == "turn-1"
    assert before.tier == "B"
    assert before.status == "started"
    assert after.status == "ok"
    assert after.ts_end_ns is not None
    assert before.ts_end_ns is None

    request_attrs = before.attrs.get("request")
    assert isinstance(request_attrs, dict)
    assert "secret user prompt" not in json.dumps(request_attrs)
    response_attrs = after.attrs.get("response")
    assert isinstance(response_attrs, dict)
    assert response_attrs.get("status_code") == 200
    assert provider_call.kind == "provider.call"
    assert provider_call.span_id == before.span_id
    call_attrs = provider_call.attrs
    assert call_attrs.get("transport") == ctx.transport
    assert call_attrs.get("status") == "ok"


def test_build_sevn_anthropic_client_sets_base_url_and_timeout() -> None:
    client = build_sevn_anthropic_client(
        proxy_base="http://proxy.test/",
        shared_secret="bridge-secret",
        trace=None,
        redactor=None,
    )
    assert str(client.base_url).rstrip("/") == "http://proxy.test"
    assert client.timeout.read == 120.0


def test_build_sevn_openai_client_delegates_to_anthropic_builder() -> None:
    client = build_sevn_openai_client(
        proxy_base="http://proxy.test",
        shared_secret="openai-bridge",
        trace=None,
        redactor=None,
    )
    assert str(client.base_url).rstrip("/") == "http://proxy.test"
    hooks = client.event_hooks
    assert hooks is not None
    assert "request" in hooks
    assert "response" in hooks


def test_redact_httpx_request_snapshot_byte_parity_with_transport_reference() -> None:
    transport = AnthropicTransport(
        proxy_base_url="http://proxy.test",
        extra_headers={PROXY_TOKEN_HEADER: "proxy-shared-secret"},
    )
    model_id = str(_SECRET_BODY["model"])
    wire_headers = transport.auth_header(model_id)
    request = httpx.Request(
        "POST",
        "http://proxy.test/llm/anthropic/messages",
        headers=wire_headers,
        json=_SECRET_BODY,
    )
    reference = redact_proxy_transport_request(
        transport,
        model_id=model_id,
        body=_SECRET_BODY,
    )
    bridge = redact_httpx_request_snapshot(request)
    assert json.dumps(reference, sort_keys=True) == json.dumps(bridge, sort_keys=True)


@pytest.mark.skipif(
    os.environ.get("SEVN_GOLDEN_LLM") != "1",
    reason="opt-in live proxy smoke (W2.5)",
)
@pytest.mark.asyncio
async def test_live_anthropic_round_trip_through_proxy_smoke() -> None:
    """Optional live smoke: requires running proxy + provider keys (W2.5)."""
    pytest.importorskip("anthropic")
    from anthropic import AsyncAnthropic
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    proxy_base = os.environ.get("SEVN_PROXY_URL", "").strip()
    if not proxy_base:
        pytest.skip("SEVN_PROXY_URL unset")

    shared_secret = resolve_proxy_shared_secret()
    http_client = build_sevn_anthropic_client(
        proxy_base=proxy_base,
        shared_secret=shared_secret,
        trace=None,
        redactor=TraceRedactionPolicy.from_defaults(),
    )
    anthropic_client = AsyncAnthropic(
        base_url=proxy_base.rstrip("/"),
        http_client=http_client,
        api_key="proxy-injected",
    )
    provider = AnthropicProvider(
        anthropic_client=anthropic_client,
        base_url=proxy_base.rstrip("/"),
    )
    model = AnthropicModel("claude-sonnet-4-20250514", provider=provider)
    try:
        response = await model.request([], None)
    finally:
        await http_client.aclose()
    assert any(getattr(part, "content", None) for part in response.parts)
