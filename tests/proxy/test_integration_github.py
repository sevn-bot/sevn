"""Tests for proxy ``POST /integration`` GitHub forwarder (Wave W2)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from sevn.proxy.app import create_app
from sevn.proxy.settings import ProxySettings


def _settings(**kwargs: str | None) -> ProxySettings:
    return ProxySettings(
        anthropic_api_key=kwargs.get("anthropic_api_key") or "ak",
        openai_api_key=kwargs.get("openai_api_key") or "ok",
        proxy_shared_secret=kwargs.get("proxy_shared_secret"),
    )


@pytest.mark.anyio
async def test_integration_github_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing GitHub token returns 503 with credential detail."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    app = create_app(settings=_settings())
    app.state.secrets_cache = None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/integration",
            json={
                "service": "github",
                "method": "pulls.list",
                "args": {"owner": "acme", "repo": "app"},
            },
        )
    assert resp.status_code == 503
    assert "token" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_integration_github_pulls_list_forwards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``pulls.list`` GETs GitHub pulls and wraps array as ``items``."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    captured: dict[str, Any] = {}

    async def fake_github_request(
        *,
        method: str,
        path: str,
        token: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        _ = (token, json_body)
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        return 200, [{"number": 7, "title": "Fix"}]

    monkeypatch.setattr(
        "sevn.proxy.integration.github._github_request",
        fake_github_request,
    )

    app = create_app(settings=_settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/integration",
            json={
                "service": "github",
                "method": "pulls.list",
                "args": {"owner": "acme", "repo": "app", "state": "open"},
            },
        )
    assert resp.status_code == 200
    assert resp.json()["items"][0]["number"] == 7
    assert captured["method"] == "GET"
    assert captured["path"] == "/repos/acme/app/pulls"
    assert captured["params"] == {"state": "open"}
