"""Functional proxy route tests for per-provider credentials (W1 contracts 6-10; green after W3)."""

from __future__ import annotations

import httpx
import pytest

from sevn.config.defaults import DEFAULT_MINIMAX_ANTHROPIC_BASE_URL
from sevn.config.model_resolution import resolve_wire_model_id
from sevn.config.workspace_config import WorkspaceConfig
from sevn.proxy.app import create_app
from sevn.proxy.credentials import ProviderCredentialEntry, ProviderCredentials
from sevn.proxy.settings import ProxySettings


def _dual_provider_workspace() -> WorkspaceConfig:
    """Workspace mixing MiniMax and Anthropic on the Anthropic transport route."""
    return WorkspaceConfig.minimal(
        providers={
            "tier_default": {
                "triager": "minimax/MiniMax-M2",
                "B": "anthropic/claude-3-5-sonnet",
            },
            "minimax": {
                "api_key": "${SECRET:SEVN_SECRET_MINIMAX}",
                "base_url": "https://api.minimax.io/anthropic/v1",
            },
            "anthropic": {
                "api_key": "${SECRET:SEVN_SECRET_ANTHROPIC}",
            },
        },
    )


def _attach_provider_credentials(app: object) -> None:
    """Simulate W3 boot wiring until handlers read ``app.state.provider_credentials``."""
    app.state.provider_credentials = ProviderCredentials(
        by_name={
            "minimax": ProviderCredentialEntry(
                api_key="sk-minimax-correct",
                anthropic_base_url="https://api.minimax.io/anthropic/v1",
            ),
            "anthropic": ProviderCredentialEntry(
                api_key="sk-anthropic-correct",
                anthropic_base_url="https://api.anthropic.com",
            ),
            "openai": ProviderCredentialEntry(
                api_key="sk-openai-correct",
                openai_base_url="https://api.openai.com/v1",
            ),
        },
    )


@pytest.mark.anyio
async def test_mixed_providers_anthropic_route_sends_per_provider_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contract 6 (core bug): distinct keys per provider on ``/llm/anthropic/messages``."""
    captures: list[dict[str, str]] = []

    async def capture_post_json(**kwargs: object) -> httpx.Response:
        hdrs = kwargs["headers"]
        body = kwargs["body"]
        assert isinstance(hdrs, dict)
        assert isinstance(body, dict)
        captures.append(
            {
                "key": str(hdrs.get("x-api-key", "")),
                "wire_model": str(body.get("model", "")),
            }
        )
        return httpx.Response(200, json={"usage": {"input_tokens": 1, "output_tokens": 1}})

    monkeypatch.setattr("sevn.proxy.app.post_json", capture_post_json)
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="sk-wrong-for-minimax",
            openai_api_key="sk-minimax-bucket",
        ),
        workspace_config=_dual_provider_workspace(),
    )
    _attach_provider_credentials(app)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        minimax_resp = await client.post(
            "/llm/anthropic/messages",
            json={"model": "minimax/MiniMax-M2", "messages": []},
        )
        anthropic_resp = await client.post(
            "/llm/anthropic/messages",
            json={"model": "anthropic/claude-3-5-sonnet", "messages": []},
        )

    assert minimax_resp.status_code == 200
    assert anthropic_resp.status_code == 200
    assert len(captures) == 2
    minimax_cap = next(
        c for c in captures if c["wire_model"] == resolve_wire_model_id("minimax/MiniMax-M2")
    )
    anthropic_cap = next(c for c in captures if "claude" in c["wire_model"])
    assert minimax_cap["key"] == "sk-minimax-correct"
    assert anthropic_cap["key"] == "sk-anthropic-correct"


@pytest.mark.anyio
async def test_mixed_providers_openai_chat_route_sends_per_provider_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contract 6: distinct keys when MiniMax and OpenAI share ``/llm/openai/chat/completions``."""
    captures: list[dict[str, str]] = []

    async def capture_post_json(**kwargs: object) -> httpx.Response:
        hdrs = kwargs["headers"]
        body = kwargs["body"]
        assert isinstance(hdrs, dict)
        assert isinstance(body, dict)
        auth = str(hdrs.get("authorization", ""))
        captures.append(
            {
                "bearer": auth.removeprefix("Bearer ").strip(),
                "wire_model": str(body.get("model", "")),
            }
        )
        return httpx.Response(200, json={"id": "chatcmpl"})

    monkeypatch.setattr("sevn.proxy.app.post_json", capture_post_json)
    ws = WorkspaceConfig.minimal(
        providers={
            "minimax": {
                "api_key": "${SECRET:SEVN_SECRET_MINIMAX}",
                "openai_base_url": "https://api.minimax.io/v1",
            },
            "openai": {"api_key": "${SECRET:SEVN_SECRET_OPENAI}"},
        },
    )
    app = create_app(
        settings=ProxySettings(
            openai_api_key="sk-wrong-for-minimax",
            anthropic_api_key="sk-openai-bucket-fallback",
            openai_base_url="https://api.openai.com/v1",
        ),
        workspace_config=ws,
    )
    app.state.provider_credentials = ProviderCredentials(
        by_name={
            "minimax": ProviderCredentialEntry(
                api_key="sk-minimax-chat",
                openai_base_url="https://api.minimax.io/v1",
            ),
            "openai": ProviderCredentialEntry(
                api_key="sk-openai-chat",
                openai_base_url="https://api.openai.com/v1",
            ),
        },
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/llm/openai/chat/completions",
            json={"model": "minimax/MiniMax-M3", "messages": []},
        )
        await client.post(
            "/llm/openai/chat/completions",
            json={"model": "openai/gpt-4o", "messages": []},
        )

    assert len(captures) == 2
    minimax_cap = next(
        c for c in captures if c["wire_model"] == resolve_wire_model_id("minimax/MiniMax-M3")
    )
    openai_cap = next(c for c in captures if "gpt-4o" in c["wire_model"])
    assert minimax_cap["bearer"] == "sk-minimax-chat"
    assert openai_cap["bearer"] == "sk-openai-chat"


@pytest.mark.anyio
async def test_two_bucket_fallback_without_provider_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contract 7 (D4): no ``providers.<name>.api_key`` keeps today's bucket behavior."""
    captured_key: str | None = None

    async def capture_post_json(**kwargs: object) -> httpx.Response:
        nonlocal captured_key
        hdrs = kwargs["headers"]
        assert isinstance(hdrs, dict)
        captured_key = str(hdrs.get("x-api-key", ""))
        return httpx.Response(200, json={"usage": {"input_tokens": 1, "output_tokens": 1}})

    monkeypatch.setattr("sevn.proxy.app.post_json", capture_post_json)
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="sk-anthropic-bucket",
            openai_api_key="sk-openai-bucket",
        ),
        workspace_config=WorkspaceConfig.minimal(
            providers={"tier_default": {"triager": "anthropic/claude-3-5-sonnet"}},
        ),
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/anthropic/messages",
            json={"model": "anthropic/claude-3-5-sonnet", "messages": []},
        )

    assert resp.status_code == 200
    assert captured_key == "sk-anthropic-bucket"


@pytest.mark.anyio
async def test_minimax_wire_id_and_base_url_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contract 8: MiniMax stripping + base-url resolution unchanged with provider registry."""
    captured: dict[str, object] = {}

    async def capture_post_json(**kwargs: object) -> httpx.Response:
        captured["url"] = kwargs["url"]
        captured["body"] = kwargs["body"]
        return httpx.Response(200, json={"usage": {"input_tokens": 1, "output_tokens": 1}})

    monkeypatch.setattr("sevn.proxy.app.post_json", capture_post_json)
    custom_base = "https://custom.minimax.example/anthropic/v1"
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="sk-mm",
            openai_api_key="sk-mm",
            anthropic_base_url=DEFAULT_MINIMAX_ANTHROPIC_BASE_URL,
        ),
        workspace_config=WorkspaceConfig.minimal(
            providers={"minimax": {"base_url": custom_base}},
        ),
    )
    app.state.provider_credentials = ProviderCredentials(
        by_name={
            "minimax": ProviderCredentialEntry(
                api_key="sk-mm",
                anthropic_base_url=custom_base,
            ),
        },
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/anthropic/messages",
            json={"model": "minimax/MiniMax-M2", "messages": []},
        )

    assert resp.status_code == 200
    assert captured["url"] == f"{custom_base}/messages"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == resolve_wire_model_id("minimax/MiniMax-M2")


@pytest.mark.anyio
async def test_openai_responses_unaffected_without_provider_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contract 9: ``/llm/openai/responses`` keeps bucket auth when registry is absent."""
    captured: dict[str, str] = {}

    async def capture_post_json(**kwargs: object) -> httpx.Response:
        hdrs = kwargs["headers"]
        assert isinstance(hdrs, dict)
        captured["auth"] = str(hdrs.get("authorization", ""))
        captured["url"] = str(kwargs["url"])
        return httpx.Response(200, json={"id": "resp-1"})

    monkeypatch.setattr("sevn.proxy.app.post_json", capture_post_json)
    app = create_app(
        settings=ProxySettings(
            openai_api_key="sk-responses",
            openai_base_url="https://api.openai.com/v1",
        ),
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/llm/openai/responses", json={"model": "gpt-4o", "input": "hi"})

    assert resp.status_code == 200
    assert captured["auth"] == "Bearer sk-responses"
    assert captured["url"] == "https://api.openai.com/v1/responses"


@pytest.mark.anyio
async def test_bedrock_converse_unaffected_without_provider_registry() -> None:
    """Contract 9: ``/llm/bedrock/converse`` still 503 without AWS creds (unchanged path)."""
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="sk-a",
            openai_api_key="sk-o",
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/llm/bedrock/converse", json={"modelId": "anthropic.claude-3"})

    assert resp.status_code == 503


@pytest.mark.anyio
async def test_503_detail_names_provider_when_credential_unresolved() -> None:
    """Contract 10 (D7): unresolved provider credential returns 503 naming the provider."""
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key=None,
            openai_api_key=None,
        ),
        workspace_config=WorkspaceConfig.minimal(
            providers={"minimax": {"base_url": "https://api.minimax.io/anthropic/v1"}},
        ),
    )
    app.state.provider_credentials = ProviderCredentials(by_name={})

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/anthropic/messages",
            json={"model": "minimax/MiniMax-M2", "messages": []},
        )

    assert resp.status_code == 503
    detail = str(resp.json().get("detail", "")).lower()
    assert "minimax" in detail
    assert "credential" in detail or "configured" in detail
