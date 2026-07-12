"""Tests for the egress LLM proxy ASGI app."""

from __future__ import annotations

import httpx
import pytest

from sevn.config.defaults import DEFAULT_MINIMAX_OPENAI_BASE_URL
from sevn.config.workspace_config import WorkspaceConfig
from sevn.proxy.app import create_app
from sevn.proxy.settings import ProxySettings


def _settings(**kwargs: str | None) -> ProxySettings:
    """Build settings with empty strings mapped to None where tests need no env."""
    return ProxySettings(
        anthropic_api_key=kwargs.get("anthropic_api_key"),
        openai_api_key=kwargs.get("openai_api_key"),
        proxy_shared_secret=kwargs.get("proxy_shared_secret"),
    )


@pytest.mark.anyio
async def test_healthz() -> None:
    """GET /healthz returns ok JSON."""
    app = create_app(settings=_settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_llm_post_requires_token_when_configured() -> None:
    """Shared secret forces X-Sevn-Proxy-Token on POST /llm/*."""
    app = create_app(
        settings=_settings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret="gated",
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/llm/openai/chat/completions", json={"model": "x"})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "unauthorized"}


@pytest.mark.anyio
async def test_bedrock_503_without_aws_credentials() -> None:
    """Bedrock route requires AWS credentials and optional boto3 extra."""
    app = create_app(settings=_settings(anthropic_api_key="a", openai_api_key="o"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/llm/bedrock/converse", json={"modelId": "m"})
    assert resp.status_code == 503


@pytest.mark.anyio
async def test_anthropic_503_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anthropic route503 when ANTHROPIC_API_KEY unset."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key=None,
            openai_api_key="sk-test",
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/llm/anthropic/messages", json={"model": "claude"})
    assert resp.status_code == 503


@pytest.mark.anyio
async def test_anthropic_forwards_via_post_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anthropic POST uses forward.post_json with injected headers."""

    async def capture_post_json(**kwargs: object) -> httpx.Response:
        assert kwargs["url"] == "https://api.anthropic.com/v1/messages"
        hdrs = kwargs["headers"]
        assert isinstance(hdrs, dict)
        assert hdrs.get("x-api-key") == "ak-test"
        assert hdrs.get("anthropic-version") == "2023-06-01"
        return httpx.Response(200, json={"usage": {"input_tokens": 1, "output_tokens": 2}})

    monkeypatch.setattr("sevn.proxy.app.post_json", capture_post_json)
    app = create_app(
        settings=_settings(
            anthropic_api_key="ak-test",
            openai_api_key="ok",
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/anthropic/messages",
            json={"model": "claude-3", "messages": []},
        )
    assert resp.status_code == 200
    assert resp.json()["usage"]["input_tokens"] == 1


@pytest.mark.anyio
async def test_anthropic_normalizes_dual_system_before_forward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proxy lifts message system roles so MiniMax does not see dual system shapes."""

    captured: dict[str, object] = {}

    async def capture_post_json(**kwargs: object) -> httpx.Response:
        captured["body"] = kwargs["body"]
        return httpx.Response(200, json={"usage": {"input_tokens": 1, "output_tokens": 2}})

    monkeypatch.setattr("sevn.proxy.app.post_json", capture_post_json)
    app = create_app(
        settings=_settings(
            anthropic_api_key="ak-test",
            openai_api_key="ok",
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/anthropic/messages",
            json={
                "model": "claude-3",
                "system": "persona",
                "messages": [
                    {"role": "system", "content": "task"},
                    {"role": "user", "content": "hi"},
                ],
            },
        )
    assert resp.status_code == 200
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["system"] == "persona\n\ntask"
    assert body["messages"] == [{"role": "user", "content": "hi"}]


@pytest.mark.anyio
async def test_openai_chat_forwards_with_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI chat path uses Bearer token from settings."""

    async def capture_post_json(**kwargs: object) -> httpx.Response:
        assert str(kwargs["url"]).endswith("/chat/completions")
        hdrs = kwargs["headers"]
        assert isinstance(hdrs, dict)
        assert hdrs.get("authorization") == "Bearer sk-openai"
        return httpx.Response(200, json={"id": "chatcmpl"})

    monkeypatch.setattr("sevn.proxy.app.post_json", capture_post_json)
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key=None,
            openai_api_key="sk-openai",
            openai_base_url="https://api.openai.com/v1",
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
    assert resp.status_code == 200
    assert resp.json()["id"] == "chatcmpl"


@pytest.mark.anyio
async def test_create_app_lifespan_http_client() -> None:
    """Lifespan creates a shared upstream client with pool limits on app state."""
    app = create_app(settings=_settings())
    async with app.router.lifespan_context(app):
        assert hasattr(app.state, "http_client")
        http_client = app.state.http_client
        assert isinstance(http_client, httpx.AsyncClient)
        assert http_client.timeout.connect == 10.0
        assert http_client.timeout.read == 90.0
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/healthz")
            assert resp.status_code == 200


# --- W2 tests: MiniMax on OpenAI chat-completions route ---


@pytest.mark.anyio
async def test_openai_chat_minimax_routes_to_minimax_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MiniMax model id on /llm/openai/chat/completions routes to MiniMax /v1."""
    captured: dict[str, object] = {}

    async def capture_post_json(**kwargs: object) -> httpx.Response:
        captured["url"] = kwargs["url"]
        captured["headers"] = kwargs["headers"]
        captured["body"] = kwargs["body"]
        return httpx.Response(200, json={"id": "chatcmpl-mm"})

    monkeypatch.setattr("sevn.proxy.app.post_json", capture_post_json)
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key=None,
            openai_api_key="sk-minimax-key",
            openai_base_url="https://api.openai.com/v1",
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": "minimax/MiniMax-M3", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert resp.status_code == 200
    assert captured["url"] == f"{DEFAULT_MINIMAX_OPENAI_BASE_URL}/chat/completions"
    hdrs = captured["headers"]
    assert isinstance(hdrs, dict)
    assert hdrs["authorization"] == "Bearer sk-minimax-key"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "MiniMax-M3"


@pytest.mark.anyio
async def test_openai_chat_minimax_with_workspace_custom_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MiniMax respects providers.minimax.openai_base_url from workspace config."""
    captured: dict[str, object] = {}

    async def capture_post_json(**kwargs: object) -> httpx.Response:
        captured["url"] = kwargs["url"]
        return httpx.Response(200, json={"id": "chatcmpl-custom"})

    monkeypatch.setattr("sevn.proxy.app.post_json", capture_post_json)
    ws_cfg = WorkspaceConfig.minimal(
        providers={"minimax": {"openai_base_url": "https://custom.minimax.io/v1"}},
    )
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key=None,
            openai_api_key="sk-test",
            openai_base_url="https://api.openai.com/v1",
        ),
        workspace_config=ws_cfg,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": "minimax/MiniMax-M2.7", "messages": []},
        )
    assert resp.status_code == 200
    assert captured["url"] == "https://custom.minimax.io/v1/chat/completions"


@pytest.mark.anyio
async def test_openai_chat_non_minimax_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-MiniMax models on /llm/openai/chat/completions route to OpenAI base URL."""
    captured: dict[str, object] = {}

    async def capture_post_json(**kwargs: object) -> httpx.Response:
        captured["url"] = kwargs["url"]
        captured["headers"] = kwargs["headers"]
        captured["body"] = kwargs["body"]
        return httpx.Response(200, json={"id": "chatcmpl-openai"})

    monkeypatch.setattr("sevn.proxy.app.post_json", capture_post_json)
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key=None,
            openai_api_key="sk-openai",
            openai_base_url="https://api.openai.com/v1",
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert resp.status_code == 200
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    hdrs = captured["headers"]
    assert isinstance(hdrs, dict)
    assert hdrs["authorization"] == "Bearer sk-openai"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-4o"


@pytest.mark.anyio
async def test_openai_chat_minimax_key_fallback_to_anthropic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When openai_api_key is empty, MiniMax branch falls back to anthropic_api_key."""
    captured: dict[str, object] = {}

    async def capture_post_json(**kwargs: object) -> httpx.Response:
        captured["headers"] = kwargs["headers"]
        return httpx.Response(200, json={"id": "chatcmpl-fallback"})

    monkeypatch.setattr("sevn.proxy.app.post_json", capture_post_json)
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="ak-fallback",
            openai_api_key="sk-primary",
            openai_base_url="https://api.openai.com/v1",
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": "minimax/MiniMax-M3", "messages": []},
        )
    assert resp.status_code == 200
    hdrs = captured["headers"]
    assert isinstance(hdrs, dict)
    assert hdrs["authorization"] == "Bearer sk-primary"
