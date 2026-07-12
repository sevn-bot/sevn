"""Codex OAuth proxy transport tests (W1.5 — D1/D7)."""

from __future__ import annotations

import httpx
import pytest
from tests.security.oauth.conftest import fake_access_jwt

from sevn.config.workspace_config import WorkspaceConfig
from sevn.proxy.app import create_app
from sevn.proxy.codex_transport import build_codex_request_headers
from sevn.proxy.credentials import ProviderCredentialEntry, ProviderCredentials
from sevn.proxy.settings import ProxySettings
from sevn.security.oauth.constants import (
    CODEX_OAUTH_ORIGINATOR,
    CODEX_RESPONSES_BASE_URL,
    CODEX_RESPONSES_PATH,
)
from sevn.security.oauth.credential import CodexOAuthCredential


def _sse_stub(sse_text: str, *, status: int = 200):
    """Return a ``post_sse_stream`` replacement that streams ``sse_text``.

    Args:
        sse_text (str): Raw ``text/event-stream`` body the stub upstream returns.
        status (int): Upstream HTTP status code.

    Returns:
        Callable: Async replacement for ``sevn.proxy.app.post_sse_stream`` that
        records its kwargs into the returned ``captured`` dict.
    """
    captured: dict[str, object] = {}

    async def capture_post_sse_stream(**kwargs: object) -> tuple[object, httpx.Response]:
        captured.update(kwargs)
        upstream = httpx.Response(
            status,
            text=sse_text,
            headers={"content-type": "text/event-stream"},
        )

        class _Client:
            async def aclose(self) -> None:
                return None

        return _Client(), upstream

    return capture_post_sse_stream, captured


_COMPLETED_SSE = (
    'data: {"type":"response.output_text.delta","delta":"ok"}\n\n'
    'data: {"type":"response.completed","response":'
    '{"id":"resp_1","model":"gpt-5.5","output":[{"type":"message","role":"assistant",'
    '"content":[{"type":"output_text","text":"ok"}]}]}}\n\n'
    "data: [DONE]\n\n"
)
"""Representative Codex SSE: an output_text delta then a terminal completed event."""


def _oauth_workspace() -> WorkspaceConfig:
    return WorkspaceConfig.minimal(
        providers={
            "tier_default": {"triager": "openai/gpt-4o"},
            "openai": {"auth_mode": "oauth"},
        },
    )


def _attach_oauth_state(app: object, *, access: str, account_id: str) -> None:
    cred = CodexOAuthCredential(
        access=access,
        refresh="rt-test",
        expires=int(__import__("time").time() * 1000) + 3_600_000,
        account_id=account_id,
    )
    app.state.codex_oauth_credential = cred
    app.state.provider_credentials = ProviderCredentials(
        by_name={
            "openai": ProviderCredentialEntry(
                api_key=None,
                openai_base_url="https://api.openai.com/v1",
            ),
        },
    )


@pytest.mark.anyio
async def test_oauth_mode_targets_codex_responses_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``auth_mode=oauth`` forwards to ``chatgpt.com/backend-api/codex/responses``."""
    stub, captured = _sse_stub(_COMPLETED_SSE)
    monkeypatch.setattr("sevn.proxy.app.post_sse_stream", stub)
    access = fake_access_jwt(account_id="acct-proxy-1")
    app = create_app(
        settings=ProxySettings(openai_api_key=None, anthropic_api_key=None),
        workspace_config=_oauth_workspace(),
    )
    _attach_oauth_state(app, access=access, account_id="acct-proxy-1")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": "openai/gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert resp.status_code == 200
    url = str(captured.get("url", ""))
    assert url == f"{CODEX_RESPONSES_BASE_URL}{CODEX_RESPONSES_PATH}"


@pytest.mark.anyio
async def test_oauth_mode_injects_codex_headers_and_removes_x_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proxy injects Bearer + ``chatgpt-account-id`` + beta/originator; drops ``x-api-key``."""
    stub, captured = _sse_stub(_COMPLETED_SSE)
    monkeypatch.setattr("sevn.proxy.app.post_sse_stream", stub)
    access = fake_access_jwt(account_id="acct-hdr")
    app = create_app(
        settings=ProxySettings(openai_api_key="sk-should-not-leak"),
        workspace_config=_oauth_workspace(),
    )
    _attach_oauth_state(app, access=access, account_id="acct-hdr")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/llm/openai/chat/completions",
            json={"model": "openai/gpt-4o", "messages": []},
            headers={"x-api-key": "must-be-stripped"},
        )

    hdrs = captured.get("headers")
    assert isinstance(hdrs, dict)
    assert hdrs.get("authorization") == f"Bearer {access}"
    assert hdrs.get("chatgpt-account-id") == "acct-hdr"
    assert hdrs.get("OpenAI-Beta") == "responses=experimental"
    assert hdrs.get("originator") == CODEX_OAUTH_ORIGINATOR
    assert hdrs.get("accept") == "text/event-stream"
    assert "x-api-key" not in {k.lower(): v for k, v in hdrs.items()}


@pytest.mark.anyio
async def test_oauth_mode_enforces_store_false_and_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex body includes ``store=false``, ``instructions``, and reasoning include."""
    stub, captured = _sse_stub(_COMPLETED_SSE)
    monkeypatch.setattr("sevn.proxy.app.post_sse_stream", stub)
    app = create_app(
        settings=ProxySettings(openai_api_key=None),
        workspace_config=_oauth_workspace(),
    )
    _attach_oauth_state(
        app,
        access=fake_access_jwt(account_id="acct-body"),
        account_id="acct-body",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/llm/openai/chat/completions",
            json={"model": "openai/gpt-4o", "messages": [{"role": "user", "content": "ping"}]},
        )

    body = captured.get("body")
    assert isinstance(body, dict)
    assert body.get("store") is False
    assert body.get("instructions")
    assert "reasoning.encrypted_content" in (body.get("include") or [])


@pytest.mark.anyio
async def test_api_key_mode_still_uses_chat_completions_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D4: ``auth_mode=api_key`` (default) does not regress chat-completions forwarding."""
    captured: dict[str, object] = {}

    async def capture_post_json(**kwargs: object) -> httpx.Response:
        captured.update(kwargs)
        return httpx.Response(200, json={"id": "chatcmpl"})

    monkeypatch.setattr("sevn.proxy.app.post_json", capture_post_json)
    ws = WorkspaceConfig.minimal(
        providers={"openai": {"api_key": "${SECRET:SEVN_SECRET_OPENAI}"}},
    )
    app = create_app(
        settings=ProxySettings(openai_api_key="sk-openai-key"),
        workspace_config=ws,
    )
    app.state.provider_credentials = ProviderCredentials(
        by_name={"openai": ProviderCredentialEntry(api_key="sk-openai-key")},
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": "openai/gpt-4o", "messages": []},
        )
    assert resp.status_code == 200
    url = str(captured.get("url", ""))
    assert url.endswith("/chat/completions")
    hdrs = captured.get("headers")
    assert isinstance(hdrs, dict)
    assert hdrs.get("authorization") == "Bearer sk-openai-key"


@pytest.mark.anyio
async def test_api_key_env_bucket_unaffected_when_not_oauth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SEVN_PROVIDER_API_KEY`` / route bucket path unchanged without ``auth_mode=oauth``."""
    captured: dict[str, object] = {}

    async def capture_post_json(**kwargs: object) -> httpx.Response:
        captured["headers"] = kwargs.get("headers")
        return httpx.Response(200, json={"id": "chatcmpl"})

    monkeypatch.setattr("sevn.proxy.app.post_json", capture_post_json)
    app = create_app(
        settings=ProxySettings(openai_api_key="sk-from-env"),
        workspace_config=WorkspaceConfig.minimal(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/llm/openai/chat/completions",
            json={"model": "openai/gpt-4o", "messages": []},
        )
    hdrs = captured.get("headers")
    assert isinstance(hdrs, dict)
    assert hdrs.get("authorization") == "Bearer sk-from-env"


# --- P1 regression: framing/hop-by-hop header strip in the header builder ----


def test_build_codex_request_headers_strips_framing_and_keeps_required() -> None:
    """Inbound framing/auth headers are dropped; required Codex headers survive (P1)."""
    hdrs = build_codex_request_headers(
        access_token="jwt-abc",
        account_id="acct-1",
        incoming={
            "host": "127.0.0.1:8787",
            "content-length": "285",
            "accept-encoding": "gzip",
            "x-api-key": "k",
        },
    )
    lowered = {k.lower() for k in hdrs}
    # None of the inbound framing / auth headers survive.
    for dropped in ("host", "content-length", "accept-encoding", "x-api-key"):
        assert dropped not in lowered, f"{dropped} leaked into upstream headers"
    # Required Codex headers are present and correct.
    assert hdrs["authorization"] == "Bearer jwt-abc"
    assert hdrs["chatgpt-account-id"] == "acct-1"
    assert hdrs["OpenAI-Beta"] == "responses=experimental"
    assert hdrs["originator"] == CODEX_OAUTH_ORIGINATOR
    assert hdrs["content-type"] == "application/json"


def test_build_codex_request_headers_strips_uppercase_framing() -> None:
    """Header stripping is case-insensitive (e.g. ``Content-Length``)."""
    hdrs = build_codex_request_headers(
        access_token="jwt",
        account_id="a",
        incoming={"Content-Length": "9", "Host": "evil", "Connection": "keep-alive"},
    )
    lowered = {k.lower() for k in hdrs}
    assert "content-length" not in lowered
    assert "host" not in lowered
    assert "connection" not in lowered


def test_build_codex_request_headers_forwards_benign_inbound() -> None:
    """A non-framing inbound header (e.g. ``session_id``) is still forwarded."""
    hdrs = build_codex_request_headers(
        access_token="jwt",
        account_id="a",
        incoming={"session_id": "sess-1", "host": "drop"},
    )
    assert hdrs.get("session_id") == "sess-1"
    assert "host" not in {k.lower() for k in hdrs}


# --- P4 integration: clean OAuth round-trip with realistic inbound headers ---


@pytest.mark.anyio
async def test_oauth_route_round_trip_non_stream_with_framing_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: inbound host/content-length never reach the upstream (stream=False)."""
    stub, captured = _sse_stub(_COMPLETED_SSE)
    monkeypatch.setattr("sevn.proxy.app.post_sse_stream", stub)
    access = fake_access_jwt(account_id="acct-rt")
    app = create_app(
        settings=ProxySettings(openai_api_key=None, anthropic_api_key=None),
        workspace_config=_oauth_workspace(),
    )
    _attach_oauth_state(app, access=access, account_id="acct-rt")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": "openai/gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers={"content-length": "285", "x-api-key": "drop"},
        )
    assert resp.status_code == 200
    hdrs = captured.get("headers")
    assert isinstance(hdrs, dict)
    lowered = {k.lower() for k in hdrs}
    assert "host" not in lowered
    assert "content-length" not in lowered
    assert "x-api-key" not in lowered
    assert hdrs.get("authorization") == f"Bearer {access}"


@pytest.mark.anyio
async def test_oauth_non_stream_forces_upstream_stream_and_buffers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stream=False caller streams upstream (stream=true) and gets buffered JSON.

    Reproduces the production 400 ``{"detail":"Stream must be set to true"}``: the
    proxy must send ``stream=true`` to Codex even when the caller asked for a
    non-streaming completion, then assemble the SSE into one chat-completion JSON.
    """
    stub, captured = _sse_stub(_COMPLETED_SSE)
    monkeypatch.setattr("sevn.proxy.app.post_sse_stream", stub)
    access = fake_access_jwt(account_id="acct-buf")
    app = create_app(
        settings=ProxySettings(openai_api_key=None, anthropic_api_key=None),
        workspace_config=_oauth_workspace(),
    )
    _attach_oauth_state(app, access=access, account_id="acct-buf")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": "openai/gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
    # (a) the upstream request carried stream=true
    upstream_body = captured.get("body")
    assert isinstance(upstream_body, dict)
    assert upstream_body.get("stream") is True
    # (b) a non-streaming chat-completions JSON (200) with the assembled content
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    payload = resp.json()
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["message"]["content"] == "ok"
    # (c) NOT a 400
    assert resp.status_code != 400


@pytest.mark.anyio
async def test_oauth_non_stream_aggregates_from_deltas_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Codex emits only output_text deltas (no completed event), text is assembled."""
    sse = (
        'data: {"type":"response.output_text.delta","delta":"Hello"}\n\n'
        'data: {"type":"response.output_text.delta","delta":", world"}\n\n'
        "data: [DONE]\n\n"
    )
    stub, _captured = _sse_stub(sse)
    monkeypatch.setattr("sevn.proxy.app.post_sse_stream", stub)
    access = fake_access_jwt(account_id="acct-delta")
    app = create_app(
        settings=ProxySettings(openai_api_key=None, anthropic_api_key=None),
        workspace_config=_oauth_workspace(),
    )
    _attach_oauth_state(app, access=access, account_id="acct-delta")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": "openai/gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "Hello, world"


@pytest.mark.anyio
async def test_oauth_non_stream_passes_through_upstream_4xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An upstream 4xx during the non-stream path is passed through (not swallowed)."""
    stub, _captured = _sse_stub('{"detail":"boom"}', status=400)
    monkeypatch.setattr("sevn.proxy.app.post_sse_stream", stub)
    access = fake_access_jwt(account_id="acct-4xx")
    app = create_app(
        settings=ProxySettings(openai_api_key=None, anthropic_api_key=None),
        workspace_config=_oauth_workspace(),
    )
    _attach_oauth_state(app, access=access, account_id="acct-4xx")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": "openai/gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert resp.status_code == 400
    assert "boom" in resp.text


@pytest.mark.anyio
async def test_oauth_route_round_trip_stream_with_framing_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: inbound framing headers never reach the upstream (stream=True)."""
    captured: dict[str, object] = {}

    async def capture_post_sse_stream(**kwargs: object) -> tuple[object, httpx.Response]:
        captured.update(kwargs)
        upstream = httpx.Response(200, text="", headers={"content-type": "text/event-stream"})

        class _Client:
            async def aclose(self) -> None:
                return None

        return _Client(), upstream

    monkeypatch.setattr("sevn.proxy.app.post_sse_stream", capture_post_sse_stream)
    access = fake_access_jwt(account_id="acct-stream")
    app = create_app(
        settings=ProxySettings(openai_api_key=None, anthropic_api_key=None),
        workspace_config=_oauth_workspace(),
    )
    _attach_oauth_state(app, access=access, account_id="acct-stream")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={
                "model": "openai/gpt-4o",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
            headers={"content-length": "999", "x-api-key": "drop"},
        )
        await resp.aread()
    assert resp.status_code == 200
    hdrs = captured.get("headers")
    assert isinstance(hdrs, dict)
    lowered = {k.lower() for k in hdrs}
    assert "host" not in lowered
    assert "content-length" not in lowered
    assert "x-api-key" not in lowered


# --- Tool-call round-trips (buffered + streaming) ---------------------------

_TOOLS_REQUEST: dict[str, object] = {
    "model": "openai/gpt-4o",
    "messages": [{"role": "user", "content": "weather in SF?"}],
    "tools": [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the weather.",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
        },
    ],
}

# Real Codex framing: the function call arrives via ``output_item.added`` then
# ``output_item.done`` (carrying complete arguments); the terminal
# ``response.completed`` re-includes an EMPTY ``output``.
_TOOL_CALL_COMPLETED_SSE = (
    'data: {"type":"response.output_item.added","output_index":0,'
    '"item":{"type":"function_call","call_id":"call_1","name":"get_weather"}}\n\n'
    'data: {"type":"response.function_call_arguments.delta","output_index":0,'
    '"delta":"{\\"city\\":\\"SF\\"}"}\n\n'
    'data: {"type":"response.output_item.done","output_index":0,'
    '"item":{"type":"function_call","call_id":"call_1","name":"get_weather",'
    '"arguments":"{\\"city\\":\\"SF\\"}"}}\n\n'
    'data: {"type":"response.completed","response":'
    '{"id":"resp_tool","model":"gpt-5.5","output":[]}}\n\n'
    "data: [DONE]\n\n"
)


@pytest.mark.anyio
async def test_oauth_buffered_tool_call_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Buffered path: tools reach Codex (flattened) and the client gets ``tool_calls``."""
    stub, captured = _sse_stub(_TOOL_CALL_COMPLETED_SSE)
    monkeypatch.setattr("sevn.proxy.app.post_sse_stream", stub)
    access = fake_access_jwt(account_id="acct-tool")
    app = create_app(
        settings=ProxySettings(openai_api_key=None, anthropic_api_key=None),
        workspace_config=_oauth_workspace(),
    )
    _attach_oauth_state(app, access=access, account_id="acct-tool")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/llm/openai/chat/completions", json=_TOOLS_REQUEST)

    # (a) the upstream request carried the flattened Responses tools
    body = captured.get("body")
    assert isinstance(body, dict)
    tools = body.get("tools")
    assert isinstance(tools, list)
    assert tools[0]["type"] == "function"
    assert tools[0]["name"] == "get_weather"
    assert "function" not in tools[0]

    # (b) the client received OpenAI tool_calls + finish_reason="tool_calls"
    assert resp.status_code == 200
    payload = resp.json()
    choice = payload["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    tc = choice["message"]["tool_calls"][0]
    assert tc["id"] == "call_1"
    assert tc["function"]["name"] == "get_weather"
    assert tc["function"]["arguments"] == '{"city":"SF"}'


@pytest.mark.anyio
async def test_oauth_streaming_tool_call_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Streaming path: a function-call SSE yields chat ``tool_calls`` deltas to the client."""
    import json as _json

    stub, captured = _sse_stub(_TOOL_CALL_COMPLETED_SSE)
    monkeypatch.setattr("sevn.proxy.app.post_sse_stream", stub)
    access = fake_access_jwt(account_id="acct-tool-stream")
    app = create_app(
        settings=ProxySettings(openai_api_key=None, anthropic_api_key=None),
        workspace_config=_oauth_workspace(),
    )
    _attach_oauth_state(app, access=access, account_id="acct-tool-stream")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={**_TOOLS_REQUEST, "stream": True},
        )
        raw = (await resp.aread()).decode("utf-8")

    assert resp.status_code == 200
    # Upstream carried the flattened tools.
    body = captured.get("body")
    assert isinstance(body, dict)
    assert body["tools"][0]["name"] == "get_weather"
    # Client received tool_call deltas (id + name) and a terminal tool_calls finish.
    payloads = [
        _json.loads(line[len("data: ") :].strip())
        for line in raw.splitlines()
        if line.startswith("data: ") and "[DONE]" not in line
    ]
    opened = [
        tc
        for p in payloads
        for tc in p["choices"][0]["delta"].get("tool_calls", [])
        if tc.get("id")
    ]
    assert opened
    assert opened[0]["id"] == "call_1"
    assert opened[0]["function"]["name"] == "get_weather"
    assert payloads[-1]["choices"][0]["finish_reason"] == "tool_calls"
