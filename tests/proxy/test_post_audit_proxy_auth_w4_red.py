"""Batch B W4 RED — proxy fail-closed auth + scoped session tokens (#167, #168; D11, D12).

Contracts: guarded routes return 503 when ``proxy_shared_secret`` is unset; explicit
``SEVN_PROXY_ALLOW_UNAUTHENTICATED=1`` opt-in passes with warnings; ``X-Sevn-Session-Token``
accept/reject by expiry and route-family scope; ``build_sandbox_child_env`` never carries
the service secret. Fake forward-proxy env vars removed in W6 (W4.4 xfail).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import httpx
import pytest
from loguru import logger
from starlette.requests import Request

from sevn.proxy.app import create_app
from sevn.proxy.auth import llm_post_auth_failure
from sevn.proxy.settings import ProxySettings
from sevn.security.sandbox_runtime import build_sandbox_child_env

_UNCONFIGURED_DETAIL = "proxy authentication not configured"
_UNCONFIGURED_BODY = b'{"detail":"proxy authentication not configured"}'
_SERVICE_SECRET = "long-lived-service-secret-at-least-32-chars"
_SIGNING_KEY = _SERVICE_SECRET
_SANDBOX_SCOPE = "sandbox"

_XFAIL_W5 = pytest.mark.xfail(reason="green after W5: fail-closed proxy auth", strict=False)
_XFAIL_W6_SESSION = pytest.mark.xfail(reason="green after W6: scoped session tokens", strict=False)


def _request(
    *,
    method: str = "POST",
    path: str = "/llm/openai/chat/completions",
    proxy_token: str | None = None,
    session_token: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if proxy_token is not None:
        headers.append((b"x-sevn-proxy-token", proxy_token.encode()))
    if session_token is not None:
        headers.append((b"x-sevn-session-token", session_token.encode()))
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


def _mint_session_token(
    *,
    signing_key: str,
    scope: str,
    expires_at: int | None = None,
    run_id: str = "test-run",
) -> str:
    """Contract token shape for W6 ``mint/validate`` — must match implementation."""
    exp = expires_at if expires_at is not None else int(time.time()) + 3600
    payload = {"scope": scope, "exp": exp, "run_id": run_id}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    body = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    sig = hmac.new(signing_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"v1.{body}.{sig}"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/llm/openai/chat/completions"),
        ("POST", "/llm/openai/chat/completions"),
        ("GET", "/web/fetch"),
        ("POST", "/web/fetch"),
        ("GET", "/integration"),
        ("POST", "/integration"),
    ],
)
@_XFAIL_W5
def test_guarded_routes_503_when_secret_unconfigured(method: str, path: str) -> None:
    """Deleting the fail-closed branch must break this test (P4a / D11)."""
    resp = llm_post_auth_failure(_request(method=method, path=path), None)
    assert resp is not None
    assert resp.status_code == 503
    assert resp.body == _UNCONFIGURED_BODY


@pytest.mark.parametrize("secret", [None, ""])
@_XFAIL_W5
def test_guarded_routes_503_when_secret_empty(secret: str | None) -> None:
    resp = llm_post_auth_failure(_request(path="/web/fetch"), secret)
    assert resp is not None
    assert resp.status_code == 503
    assert resp.body == _UNCONFIGURED_BODY


def test_unguarded_healthz_still_open_when_secret_unconfigured() -> None:
    assert llm_post_auth_failure(_request(path="/healthz"), None) is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/llm/openai/chat/completions"),
        ("POST", "/web/fetch"),
        ("POST", "/integration"),
    ],
)
@_XFAIL_W5
async def test_proxy_app_503_on_guarded_routes_without_secret(method: str, path: str) -> None:
    app = create_app(
        settings=ProxySettings(anthropic_api_key="ak", openai_api_key="ok"),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        if path == "/web/fetch":
            resp = await client.request(method, path, json={"url": "https://example.com/"})
        elif path == "/integration":
            resp = await client.request(method, path, json={"provider": "github", "action": "noop"})
        else:
            resp = await client.request(method, path, json={"model": "x"})
    assert resp.status_code == 503
    assert resp.json() == {"detail": _UNCONFIGURED_DETAIL}


@pytest.mark.anyio
@_XFAIL_W5
async def test_allow_unauthenticated_opt_in_passes_and_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEVN_PROXY_ALLOW_UNAUTHENTICATED", "1")
    warnings: list[str] = []
    sink_id = logger.add(lambda rec: warnings.append(str(rec)), level="WARNING")
    try:
        app = create_app(
            settings=ProxySettings(anthropic_api_key="ak", openai_api_key="ok"),
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/llm/openai/chat/completions",
                json={"model": "x"},
            )
        assert resp.status_code != 503
        assert resp.json().get("detail") != _UNCONFIGURED_DETAIL
        joined = " ".join(warnings).lower()
        assert "unauthenticated" in joined or "allow_unauthenticated" in joined
    finally:
        logger.remove(sink_id)


@pytest.mark.anyio
@_XFAIL_W6_SESSION
async def test_valid_sandbox_session_token_accepted_on_web_route() -> None:
    token = _mint_session_token(signing_key=_SIGNING_KEY, scope=_SANDBOX_SCOPE)
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret=_SERVICE_SECRET,
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/web/fetch",
            json={"url": "https://example.com/"},
            headers={"X-Sevn-Session-Token": token},
        )
    assert resp.status_code != 401
    assert resp.json().get("detail") != "unauthorized"


@pytest.mark.anyio
@_XFAIL_W6_SESSION
async def test_session_token_rejects_wrong_scope_on_llm_route() -> None:
    token = _mint_session_token(signing_key=_SIGNING_KEY, scope=_SANDBOX_SCOPE)
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret=_SERVICE_SECRET,
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": "x"},
            headers={"X-Sevn-Session-Token": token},
        )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "unauthorized"}


@pytest.mark.anyio
@_XFAIL_W6_SESSION
async def test_session_token_rejects_expired() -> None:
    token = _mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=_SANDBOX_SCOPE,
        expires_at=int(time.time()) - 60,
    )
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret=_SERVICE_SECRET,
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/web/fetch",
            json={"url": "https://example.com/"},
            headers={"X-Sevn-Session-Token": token},
        )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "unauthorized"}


@pytest.mark.anyio
@_XFAIL_W6_SESSION
async def test_session_token_rejects_forged_signature() -> None:
    token = _mint_session_token(signing_key=_SIGNING_KEY, scope=_SANDBOX_SCOPE)
    forged = token[:-4] + "dead"
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret=_SERVICE_SECRET,
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/web/fetch",
            json={"url": "https://example.com/"},
            headers={"X-Sevn-Session-Token": forged},
        )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "unauthorized"}


@pytest.mark.anyio
@_XFAIL_W6_SESSION
async def test_concurrent_same_session_token_requests_consistent() -> None:
    """Same scoped credential — both replies must agree (no race bypass)."""
    token = _mint_session_token(signing_key=_SIGNING_KEY, scope=_SANDBOX_SCOPE)
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret=_SERVICE_SECRET,
        ),
    )
    transport = httpx.ASGITransport(app=app)

    async def _fetch() -> int:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/web/fetch",
                json={"url": "https://example.com/"},
                headers={"X-Sevn-Session-Token": token},
            )
            return resp.status_code

    import asyncio

    codes = await asyncio.gather(_fetch(), _fetch())
    assert codes[0] == codes[1]
    assert codes[0] != 401


def test_build_sandbox_child_env_never_injects_service_secret() -> None:
    env = build_sandbox_child_env(
        proxy_url="http://127.0.0.1:8787",
        session_token="per-run-session-token",
        workspace_mount_path="/workspace",
    )
    assert "SEVN_PROXY_SHARED_SECRET" not in env
    assert _SERVICE_SECRET not in env.values()
    for key, value in env.items():
        assert key.upper() != "X-SEVN-PROXY-TOKEN"
        assert value != _SERVICE_SECRET


@pytest.mark.xfail(reason="green after W6: drop fake proxy env vars", strict=False)
def test_build_sandbox_child_env_omits_forward_proxy_vars() -> None:
    env = build_sandbox_child_env(
        proxy_url="http://127.0.0.1:8787",
        session_token="tok",
        workspace_mount_path="/workspace",
    )
    assert "HTTP_PROXY" not in env
    assert "HTTPS_PROXY" not in env
    assert "NO_PROXY" not in env


@pytest.mark.xfail(reason="green after W6: drop fake proxy env vars", strict=False)
@pytest.mark.parametrize("var_name", ["HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"])
def test_build_sandbox_child_env_proxy_var_absent(var_name: str) -> None:
    env = build_sandbox_child_env(
        proxy_url="http://127.0.0.1:8787",
        session_token="tok",
        workspace_mount_path="/workspace",
    )
    assert var_name not in env
