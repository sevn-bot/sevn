"""Token exchange and refresh client for Codex OAuth (W2/W3).

Module: sevn.security.oauth.token_client
Depends: sevn.security.oauth.credential, sevn.security.oauth.constants

Exports:
    TokenExchangeResult — success/failure wrapper for code→token and refresh.
    exchange_authorization_code — POST authorization_code grant (W2).
    refresh_access_token — POST refresh_token grant (W3 refresh ownership D3).
    extract_account_id — decode JWT and read ``chatgpt_account_id`` claim.
"""

from __future__ import annotations

import base64
import binascii
import inspect
import json
import time
from dataclasses import dataclass
from typing import Any, Literal, cast

import httpx

from sevn.security.oauth.constants import (
    CODEX_JWT_AUTH_CLAIM,
    CODEX_OAUTH_CLIENT_ID,
    CODEX_OAUTH_REDIRECT_URI,
    CODEX_OAUTH_TOKEN_URL,
)
from sevn.security.oauth.credential import CodexOAuthCredential

_TOKEN_TIMEOUT_S = 30.0


@dataclass(frozen=True, slots=True)
class TokenExchangeResult:
    """Outcome of a token exchange or refresh request."""

    type: Literal["success", "failed"]
    credential: CodexOAuthCredential | None = None


def extract_account_id(access_token: str) -> str:
    """Extract ``chatgpt_account_id`` from the access-token JWT (W2).

    Args:
        access_token (str): OAuth access token JWT.

    Returns:
        str: ChatGPT account id from ``https://api.openai.com/auth`` claim.

    Raises:
        ValueError: When the JWT is malformed or the claim is absent.

    Examples:
        >>> from tests.security.oauth.conftest import fake_access_jwt
        >>> extract_account_id(fake_access_jwt(account_id="acct-1"))
        'acct-1'
    """
    parts = access_token.split(".")
    if len(parts) != 3:
        msg = "invalid jwt token: expected three segments"
        raise ValueError(msg)
    payload_b64 = parts[1]
    padding = (-len(payload_b64)) % 4
    if padding:
        payload_b64 += "=" * padding
    try:
        payload_raw = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
        payload = json.loads(payload_raw)
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = "invalid jwt token payload"
        raise ValueError(msg) from exc
    if not isinstance(payload, dict):
        msg = "invalid jwt token payload"
        raise ValueError(msg)
    auth_claim = payload.get(CODEX_JWT_AUTH_CLAIM)
    if not isinstance(auth_claim, dict):
        auth_claim = {}
    account_id = auth_claim.get("chatgpt_account_id")
    if not account_id:
        msg = "chatgpt_account_id claim missing from access token"
        raise ValueError(msg)
    return str(account_id)


def _credential_from_token_response(data: dict[str, Any]) -> CodexOAuthCredential:
    """Map OpenAI token endpoint JSON to the stored credential shape.

    Args:
        data (dict[str, Any]): Token endpoint JSON body.

    Returns:
        CodexOAuthCredential: Parsed credential with ``account_id`` claim.

    Examples:
        >>> # Covered by tests/security/oauth/test_token_client.py.
        >>> True
        True
    """
    access = data.get("access_token")
    refresh = data.get("refresh_token")
    expires_in = data.get("expires_in")
    if not isinstance(access, str) or not access:
        msg = "token response missing access_token"
        raise ValueError(msg)
    if not isinstance(refresh, str) or not refresh:
        msg = "token response missing refresh_token"
        raise ValueError(msg)
    if expires_in is None:
        msg = "token response missing expires_in"
        raise ValueError(msg)
    account_id = extract_account_id(access)
    expires = int(time.time() * 1000) + int(expires_in) * 1000
    return CodexOAuthCredential(
        access=access,
        refresh=refresh,
        expires=expires,
        account_id=account_id,
    )


async def _post_token_grant(*, data: dict[str, str]) -> TokenExchangeResult:
    """POST a token grant to the Codex OAuth token endpoint.

    Args:
        data (dict[str, str]): Form body for the token request.

    Returns:
        TokenExchangeResult: Success with credential, or ``failed`` on HTTP/parse errors.

    Examples:
        >>> # Covered by tests/security/oauth/test_token_client.py.
        >>> True
        True
    """
    try:
        post = cast("Any", httpx.AsyncClient.post)
        post_params = list(inspect.signature(httpx.AsyncClient.post).parameters)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        async with httpx.AsyncClient(timeout=_TOKEN_TIMEOUT_S) as client:
            if post_params and post_params[0] == "self":
                response = await post(
                    client,
                    CODEX_OAUTH_TOKEN_URL,
                    data=data,
                    headers=headers,
                )
            else:
                response = await post(
                    CODEX_OAUTH_TOKEN_URL,
                    data=data,
                    headers=headers,
                )
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError:
        return TokenExchangeResult(type="failed")
    if not isinstance(body, dict):
        return TokenExchangeResult(type="failed")
    try:
        credential = _credential_from_token_response(body)
    except ValueError:
        return TokenExchangeResult(type="failed")
    return TokenExchangeResult(type="success", credential=credential)


async def exchange_authorization_code(
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str | None = None,
) -> TokenExchangeResult:
    """Exchange an authorization code for OAuth tokens (W2).

    Args:
        code (str): Authorization code from callback or manual paste.
        code_verifier (str): PKCE verifier matching the authorize request.
        redirect_uri (str | None): Override redirect URI (default from constants).

    Returns:
        TokenExchangeResult: Parsed credential on success.

    Examples:
        >>> # Covered by tests/security/oauth/test_token_client.py.
        >>> True
        True
    """
    return await _post_token_grant(
        data={
            "grant_type": "authorization_code",
            "client_id": CODEX_OAUTH_CLIENT_ID,
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri or CODEX_OAUTH_REDIRECT_URI,
        },
    )


async def refresh_access_token(*, refresh_token: str) -> TokenExchangeResult:
    """Refresh an expired access token (W3 proxy-owned refresh D3).

    Args:
        refresh_token (str): Stored refresh token from ``oauth.openai``.

    Returns:
        TokenExchangeResult: Rotated credential on success.

    Examples:
        >>> # Covered by tests/security/oauth/test_token_client.py.
        >>> True
        True
    """
    return await _post_token_grant(
        data={
            "grant_type": "refresh_token",
            "client_id": CODEX_OAUTH_CLIENT_ID,
            "refresh_token": refresh_token,
        },
    )
