"""Batch A W1 RED — proxy SSRF + auth-all-verbs (#141; green after W4).

Contracts: block metadata/private IPs after DNS resolve; proxy shared-secret applies to
all HTTP verbs on guarded routes when configured.
"""

from __future__ import annotations

import socket
from typing import Any

import httpx
import pytest
from starlette.requests import Request

from sevn.proxy.auth import llm_post_auth_failure
from sevn.proxy.web_forward import web_fetch_json

_METADATA_IP = "169.254.169.254"
_PRIVATE_IPS = ("10.0.0.1", "192.168.1.50", "127.0.0.1", "172.16.0.9")


def _request(*, method: str = "GET", path: str = "/web/fetch", token: str | None = None) -> Request:
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


@pytest.mark.parametrize("blocked_ip", [_METADATA_IP, *_PRIVATE_IPS])
@pytest.mark.asyncio
async def test_web_fetch_blocks_resolved_private_ips(
    monkeypatch: pytest.MonkeyPatch,
    blocked_ip: str,
) -> None:
    hostname = "ssrf-target.example"

    def fake_getaddrinfo(
        host: str,
        port: Any,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[tuple[Any, ...]]:
        if host == hostname:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (blocked_ip, 443))]
        raise OSError("unexpected host")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    status, body = await web_fetch_json({"url": f"https://{hostname}/"})

    assert status in (403, 422)
    detail = str(body.get("detail", "")).lower()
    assert "private" in detail or "metadata" in detail or "blocked" in detail


@pytest.mark.parametrize(
    "literal_url",
    [
        f"http://{_METADATA_IP}/latest/meta-data/",
        "http://127.0.0.1:8787/admin",
        "http://192.168.0.1/",
    ],
)
@pytest.mark.asyncio
async def test_web_fetch_rejects_literal_private_urls(literal_url: str) -> None:
    status, body = await web_fetch_json({"url": literal_url})
    assert status in (403, 422)
    detail = str(body.get("detail", "")).lower()
    assert "private" in detail or "metadata" in detail or "blocked" in detail


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE", "PATCH"])
def test_proxy_auth_rejects_non_post_without_token(method: str) -> None:
    resp = llm_post_auth_failure(_request(method=method, path="/web/fetch", token=None), "secret")
    assert resp is not None
    assert resp.status_code == 401
    assert resp.body == b'{"detail":"unauthorized"}'


@pytest.mark.anyio
async def test_proxy_app_get_web_fetch_requires_token() -> None:
    from sevn.proxy.app import create_app
    from sevn.proxy.settings import ProxySettings

    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret="gated",
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/web/fetch", params={"url": "https://example.com"})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "unauthorized"}


def test_web_forward_validate_fetch_url_allows_public_https_regression() -> None:
    """Existing scheme/host validation must remain for public URLs."""
    from sevn.proxy.web_forward import _validate_fetch_url

    assert _validate_fetch_url("https://example.com/path") is None


def test_build_pinned_request_url_brackets_ipv6_literals() -> None:
    """IPv6 pinned addresses must be bracketed or httpx raises InvalidURL."""
    from sevn.proxy.web_forward import _build_pinned_request_url

    ipv6 = "2606:2800:220:1:248:1893:25c8:1946"
    assert _build_pinned_request_url("https://example.com/path", ipv6) == (f"https://[{ipv6}]/path")
    assert _build_pinned_request_url("https://example.com:8443/path", ipv6) == (
        f"https://[{ipv6}]:8443/path"
    )
