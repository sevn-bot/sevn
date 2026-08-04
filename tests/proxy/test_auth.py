"""Unit and integration tests for proxy shared-secret guard (`specs/07-egress-proxy.md` §2.3)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import httpx
import pytest
from starlette.requests import Request

from sevn.proxy.app import create_app
from sevn.proxy.auth import (
    PROXY_UNCONFIGURED_DETAIL,
    SESSION_SCOPE_SANDBOX,
    _is_guarded_path,
    llm_post_auth_failure,
    log_proxy_allow_unauthenticated_boot_warning,
    mint_session_token,
    proxy_allow_unauthenticated,
    validate_session_token,
)
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


def test_llm_post_auth_failure_503_when_no_secret() -> None:
    resp = llm_post_auth_failure(_request(), None)
    assert resp is not None
    assert resp.status_code == 503
    assert resp.body == b'{"detail":"proxy authentication not configured"}'
    resp_empty = llm_post_auth_failure(_request(), "")
    assert resp_empty is not None
    assert resp_empty.status_code == 503
    assert resp_empty.body == b'{"detail":"proxy authentication not configured"}'


def test_llm_post_auth_failure_rejects_non_post_without_token() -> None:
    resp = llm_post_auth_failure(_request(method="GET"), "secret")
    assert resp is not None
    assert resp.status_code == 401
    assert resp.body == b'{"detail":"unauthorized"}'


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
async def test_proxy_app_503_when_secret_unconfigured() -> None:
    app = create_app(
        settings=ProxySettings(anthropic_api_key="ak", openai_api_key="ok"),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/llm/openai/chat/completions", json={"model": "x"})
    assert resp.status_code == 503
    assert resp.json() == {"detail": PROXY_UNCONFIGURED_DETAIL}


def test_proxy_allow_unauthenticated_false_by_default() -> None:
    assert proxy_allow_unauthenticated(env={}) is False
    assert proxy_allow_unauthenticated(env={"SEVN_PROXY_ALLOW_UNAUTHENTICATED": "0"}) is False


def test_proxy_allow_unauthenticated_true_when_opt_in() -> None:
    assert proxy_allow_unauthenticated(env={"SEVN_PROXY_ALLOW_UNAUTHENTICATED": "1"}) is True


def test_proxy_unconfigured_detail_constant() -> None:
    assert PROXY_UNCONFIGURED_DETAIL == "proxy authentication not configured"


@pytest.mark.parametrize(
    ("path", "guarded"),
    [
        ("/llm/openai/chat/completions", True),
        ("/web/fetch", True),
        ("/integration", True),
        ("/healthz", False),
        ("/metrics", False),
    ],
)
def test_is_guarded_path(path: str, guarded: bool) -> None:
    assert _is_guarded_path(path) is guarded


def test_log_proxy_allow_unauthenticated_boot_warning_noop_without_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loguru import logger

    monkeypatch.delenv("SEVN_PROXY_ALLOW_UNAUTHENTICATED", raising=False)
    warnings: list[str] = []
    sink_id = logger.add(lambda rec: warnings.append(str(rec)), level="WARNING")
    try:
        log_proxy_allow_unauthenticated_boot_warning()
    finally:
        logger.remove(sink_id)
    assert warnings == []


def test_log_proxy_allow_unauthenticated_boot_warning_emits_when_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loguru import logger

    monkeypatch.setenv("SEVN_PROXY_ALLOW_UNAUTHENTICATED", "1")
    warnings: list[str] = []
    sink_id = logger.add(lambda rec: warnings.append(str(rec)), level="WARNING")
    try:
        log_proxy_allow_unauthenticated_boot_warning()
    finally:
        logger.remove(sink_id)
    joined = " ".join(warnings).lower()
    assert "unauthenticated" in joined or "allow_unauthenticated" in joined


_SIGNING_KEY = "unit-test-signing-key-at-least-32-chars"


def test_session_scope_sandbox_constant() -> None:
    assert SESSION_SCOPE_SANDBOX == "sandbox"


def test_validate_session_token_accepts_in_scope_web_path() -> None:
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-1",
        expires_at=int(time.time()) + 3600,
    )
    assert validate_session_token(token, signing_key=_SIGNING_KEY, path="/web/fetch") is True


def test_validate_session_token_rejects_wrong_scope_for_llm_path() -> None:
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-1",
        expires_at=int(time.time()) + 3600,
    )
    assert (
        validate_session_token(
            token,
            signing_key=_SIGNING_KEY,
            path="/llm/openai/chat/completions",
        )
        is False
    )


def test_validate_session_token_rejects_expired() -> None:
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-1",
        expires_at=int(time.time()) - 60,
    )
    assert validate_session_token(token, signing_key=_SIGNING_KEY, path="/web/fetch") is False


def test_validate_session_token_rejects_forged_signature() -> None:
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-1",
        expires_at=int(time.time()) + 3600,
    )
    forged = token[:-4] + "dead"
    assert validate_session_token(forged, signing_key=_SIGNING_KEY, path="/web/fetch") is False


def test_validate_session_token_rejects_empty_token_or_signing_key() -> None:
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-1",
        expires_at=int(time.time()) + 3600,
    )
    assert validate_session_token("", signing_key=_SIGNING_KEY, path="/web/fetch") is False
    assert validate_session_token(token, signing_key="", path="/web/fetch") is False
