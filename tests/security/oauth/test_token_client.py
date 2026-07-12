"""Token exchange and account-id extraction tests (W1.2)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from tests.security.oauth.conftest import b64url_json, fake_access_jwt

from sevn.security.oauth.constants import (
    CODEX_JWT_AUTH_CLAIM,
    CODEX_OAUTH_CLIENT_ID,
    CODEX_OAUTH_REDIRECT_URI,
    CODEX_OAUTH_TOKEN_URL,
)
from sevn.security.oauth.credential import CodexOAuthCredential
from sevn.security.oauth.token_client import (
    TokenExchangeResult,
    exchange_authorization_code,
    extract_account_id,
    refresh_access_token,
)


def test_token_exchange_result_success_shape() -> None:
    """``TokenExchangeResult`` carries credential on success."""
    cred = CodexOAuthCredential(
        access="at",
        refresh="rt",
        expires=1_700_000_000_000,
        account_id="acct-1",
    )
    result = TokenExchangeResult(type="success", credential=cred)
    assert result.type == "success"
    assert result.credential is cred


def test_extract_account_id_reads_jwt_claim() -> None:
    """``extract_account_id`` decodes ``chatgpt_account_id`` from access JWT."""
    token = fake_access_jwt(account_id="acct-jwt-42")
    assert extract_account_id(token) == "acct-jwt-42"


def test_extract_account_id_fails_when_claim_missing() -> None:
    """Missing ``chatgpt_account_id`` raises ``ValueError`` (W2 contract)."""
    header = b64url_json({"alg": "none"})
    payload = b64url_json({CODEX_JWT_AUTH_CLAIM: {}})
    token = f"{header}.{payload}.sig"
    with pytest.raises(ValueError, match=r"(?i)chatgpt_account_id|account"):
        extract_account_id(token)


def test_extract_account_id_fails_on_malformed_jwt() -> None:
    """Malformed JWT segments raise ``ValueError``."""
    with pytest.raises(ValueError, match=r"(?i)jwt|token|segment"):
        extract_account_id("not-a-jwt")


@pytest.mark.anyio
async def test_exchange_authorization_code_posts_form_body(
    monkeypatch: pytest.MonkeyPatch,
    token_exchange_response: dict[str, Any],
) -> None:
    """Code exchange POSTs authorization_code grant to the token URL."""
    captured: dict[str, Any] = {}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return token_exchange_response

    async def _post(url: str, *, data: dict[str, str], headers: dict[str, str]) -> _Resp:
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        return _Resp()

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)

    result = await exchange_authorization_code(code="auth-code-xyz", code_verifier="verifier-abc")
    assert captured["url"] == CODEX_OAUTH_TOKEN_URL
    assert captured["data"]["grant_type"] == "authorization_code"
    assert captured["data"]["client_id"] == CODEX_OAUTH_CLIENT_ID
    assert captured["data"]["code"] == "auth-code-xyz"
    assert captured["data"]["code_verifier"] == "verifier-abc"
    assert captured["data"]["redirect_uri"] == CODEX_OAUTH_REDIRECT_URI
    assert result.type == "success"
    assert result.credential is not None
    assert result.credential.account_id == "acct-from-token-endpoint"
    assert result.credential.refresh == "rt-from-token-endpoint"
    assert result.credential.expires > 0


@pytest.mark.anyio
async def test_exchange_authorization_code_maps_expires_in_to_ms(
    monkeypatch: pytest.MonkeyPatch,
    token_exchange_response: dict[str, Any],
) -> None:
    """``expires_in`` seconds are converted to epoch milliseconds on the credential."""

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return token_exchange_response

    async def _post(*_a: object, **_k: object) -> _Resp:
        return _Resp()

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)

    before_ms = int(__import__("time").time() * 1000)
    result = await exchange_authorization_code(code="c", code_verifier="v")
    after_ms = int(__import__("time").time() * 1000)
    assert result.credential is not None
    # expires_in=3600 → roughly now + 3600s in ms
    assert before_ms + 3_599_000 <= result.credential.expires <= after_ms + 3_601_000


@pytest.mark.anyio
async def test_refresh_access_token_posts_refresh_grant(
    monkeypatch: pytest.MonkeyPatch,
    token_exchange_response: dict[str, Any],
) -> None:
    """Refresh grant POSTs ``grant_type=refresh_token`` with client id."""
    captured: dict[str, Any] = {}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return token_exchange_response

    async def _post(url: str, *, data: dict[str, str], headers: dict[str, str]) -> _Resp:
        captured["url"] = url
        captured["data"] = data
        return _Resp()

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)

    result = await refresh_access_token(refresh_token="rt-old")
    assert captured["url"] == CODEX_OAUTH_TOKEN_URL
    assert captured["data"]["grant_type"] == "refresh_token"
    assert captured["data"]["client_id"] == CODEX_OAUTH_CLIENT_ID
    assert captured["data"]["refresh_token"] == "rt-old"
    assert result.type == "success"
    assert result.credential is not None


@pytest.mark.anyio
async def test_exchange_authorization_code_returns_failed_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP 403 (unsupported region) surfaces as ``failed`` result, not uncaught."""

    class _Resp:
        status_code = 403

        def raise_for_status(self) -> None:
            msg = "403 unsupported_country_region_territory"
            raise __import__("httpx").HTTPStatusError(
                msg,
                request=__import__("httpx").Request("POST", CODEX_OAUTH_TOKEN_URL),
                response=self,
            )

        def json(self) -> dict[str, str]:
            return {"error": "unsupported_country_region_territory"}

    async def _post(*_a: object, **_k: object) -> _Resp:
        return _Resp()

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)

    result = await exchange_authorization_code(code="c", code_verifier="v")
    assert result.type == "failed"
    assert result.credential is None
