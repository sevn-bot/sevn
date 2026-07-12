"""Tests for proxy ``POST /integration`` Cursor forwarder."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.proxy.app import create_app
from sevn.proxy.settings import ProxySettings


def _settings(**kwargs: str | None) -> ProxySettings:
    return ProxySettings(
        anthropic_api_key=kwargs.get("anthropic_api_key") or "ak",
        openai_api_key=kwargs.get("openai_api_key") or "ok",
        proxy_shared_secret=kwargs.get("proxy_shared_secret"),
    )


@pytest.mark.anyio
async def test_integration_requires_cursor_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing API key returns 503."""
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    app = create_app(settings=_settings())
    app.state.secrets_cache = None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/integration",
            json={
                "service": "cursor",
                "method": "agents.get",
                "args": {"id": "bc-1"},
            },
        )
    assert resp.status_code == 503
    assert "api key" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_integration_agents_create_forwards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """agents.create POSTs to Cursor API with Basic auth."""
    monkeypatch.setenv("CURSOR_API_KEY", "cursor_test_key")
    captured: dict[str, Any] = {}

    async def fake_cursor_request(
        *,
        method: str,
        path: str,
        api_key: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        _ = (api_key, params)
        captured["method"] = method
        captured["path"] = path
        captured["json"] = json_body
        return 200, {
            "agent": {
                "id": "bc-test",
                "status": "ACTIVE",
                "url": "https://cursor.com/agents/bc-test",
            },
            "run": {"id": "run-1", "status": "RUNNING"},
        }

    monkeypatch.setattr(
        "sevn.proxy.integration.cursor._cursor_request",
        fake_cursor_request,
    )

    app = create_app(settings=_settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/integration",
            json={
                "service": "cursor",
                "method": "agents.create",
                "args": {
                    "prompt": {"text": "add readme"},
                    "repos": [{"url": "https://github.com/o/r", "startingRef": "main"}],
                    "model": {"id": "composer-2"},
                },
            },
        )
    assert resp.status_code == 200
    assert resp.json()["agent"]["id"] == "bc-test"
    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/agents"


@pytest.mark.anyio
async def test_integration_mcp_profile_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    """mcp_profile expands from workspace config before upstream POST."""
    monkeypatch.setenv("CURSOR_API_KEY", "cursor_test_key")
    captured_json: dict[str, Any] = {}

    async def fake_cursor_request(
        *,
        method: str,
        path: str,
        api_key: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        _ = (method, path, api_key, params)
        captured_json.update(json_body or {})
        return 200, {"agent": {"id": "bc-mcp", "status": "ACTIVE", "url": "https://x"}}

    monkeypatch.setattr(
        "sevn.proxy.integration.cursor._cursor_request",
        fake_cursor_request,
    )

    ws = WorkspaceConfig(
        schema_version=1,
        skills={
            "cursor_cloud": {
                "mcp_profiles": {
                    "demo": {
                        "servers": [
                            {
                                "name": "linear",
                                "type": "sse",
                                "url": "https://mcp.linear.app/sse",
                            },
                        ],
                    },
                },
            },
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    app = create_app(settings=_settings(), workspace_config=ws)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/integration",
            json={
                "service": "cursor",
                "method": "agents.create",
                "args": {
                    "prompt": {"text": "task"},
                    "repos": [{"url": "https://github.com/o/r"}],
                    "mcp_profile": "demo",
                },
            },
        )
    assert resp.status_code == 200
    servers = captured_json.get("mcpServers")
    assert isinstance(servers, list)
    assert servers[0]["name"] == "linear"
