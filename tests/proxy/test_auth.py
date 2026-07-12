"""Unit and integration tests for proxy shared-secret guard (`specs/07-egress-proxy.md` §2.3)."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
from starlette.requests import Request

from sevn.proxy.app import create_app
from sevn.proxy.auth import llm_post_auth_failure
from sevn.proxy.settings import ProxySettings


def _request(
    *,
    method: str = "POST",
    path: str = "/llm/openai/chat/completions",
    token: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if token is not None:
        headers.append((b"x-sevn-proxy-token", token.encode()))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "headers": headers,
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


def test_llm_post_auth_failure_skips_when_no_secret() -> None:
    assert llm_post_auth_failure(_request(), None) is None
    assert llm_post_auth_failure(_request(), "") is None


def test_llm_post_auth_failure_skips_non_post() -> None:
    assert llm_post_auth_failure(_request(method="GET"), "secret") is None


def test_llm_post_auth_failure_skips_unguarded_path() -> None:
    assert llm_post_auth_failure(_request(path="/healthz"), "secret") is None


def test_llm_post_auth_failure_rejects_missing_token() -> None:
    resp = llm_post_auth_failure(_request(token=None), "secret")
    assert resp is not None
    assert resp.status_code == 401


def test_llm_post_auth_failure_rejects_wrong_token() -> None:
    resp = llm_post_auth_failure(_request(token="wrong"), "secret")
    assert resp is not None
    assert resp.status_code == 401


def test_llm_post_auth_failure_accepts_correct_token() -> None:
    assert llm_post_auth_failure(_request(token="secret"), "secret") is None


def test_llm_post_auth_failure_guarded_web_prefix() -> None:
    assert llm_post_auth_failure(_request(path="/web/fetch", token="secret"), "secret") is None
    resp = llm_post_auth_failure(_request(path="/web/fetch", token="bad"), "secret")
    assert resp is not None
    assert resp.status_code == 401


def test_llm_post_auth_failure_magic_mock_get_method() -> None:
    req = MagicMock(method="GET")
    assert llm_post_auth_failure(req, None) is None


@pytest.mark.anyio
async def test_proxy_app_accepts_correct_token() -> None:
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret="gated",
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": "x"},
            headers={"X-Sevn-Proxy-Token": "gated"},
        )
    assert resp.json().get("detail") != "unauthorized"


@pytest.mark.anyio
async def test_proxy_app_rejects_wrong_token() -> None:
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret="gated",
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": "x"},
            headers={"X-Sevn-Proxy-Token": "wrong"},
        )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "unauthorized"}


@pytest.mark.anyio
async def test_proxy_app_skips_guard_without_secret() -> None:
    app = create_app(
        settings=ProxySettings(anthropic_api_key="ak", openai_api_key="ok"),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/llm/openai/chat/completions", json={"model": "x"})
    assert resp.json().get("detail") != "unauthorized"
