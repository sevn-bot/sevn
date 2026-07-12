"""GitHub OAuth for the onboarding web wizard (`plan/onboarding-comprehensive-setup` W4, D6).

Module: sevn.onboarding.github_oauth
Depends: httpx, os, secrets, time, urllib.parse

Exports:
    build_authorize_url — GitHub authorize redirect URL.
    callback_redirect_uri — loopback callback URL for a wizard port.
    mint_oauth_state — create CSRF state (single-use).
    validate_oauth_state — consume and verify OAuth state.
    exchange_code_for_token — OAuth code → access token.
    fetch_github_user — ``GET /user`` probe for token validity.
    clear_oauth_states — test helper to reset in-memory state.
    clear_wizard_oauth_credentials — drop in-memory wizard OAuth app creds.
    set_wizard_oauth_credentials — store wizard OAuth app creds for the session.
    oauth_client_credentials — read OAuth app id/secret from env or wizard memory.
    oauth_configured — True when OAuth app credentials are available.
"""

from __future__ import annotations

import os
import secrets
import time
import urllib.parse
from typing import Any

import httpx

GITHUB_TOKEN_LOGICAL_KEY = "integration.github.token"  # nosec B105
_STATE_TTL_SECONDS = 600.0
_GITHUB_API_VERSION = "2022-11-28"

_oauth_states: dict[str, float] = {}
_wizard_oauth_credentials: dict[str, str] = {}


def set_wizard_oauth_credentials(client_id: str | None, client_secret: str | None) -> None:
    """Store OAuth app credentials for the current onboarding wizard session.

    Values live in process memory only (never written to ``sevn.json`` or the
    encrypted secrets store). Env vars remain the fallback when unset.

    Args:
        client_id (str | None): GitHub OAuth app client id.
        client_secret (str | None): GitHub OAuth app client secret.

    Examples:
        >>> set_wizard_oauth_credentials("cid", "sec")
        >>> oauth_client_credentials()[0]
        'cid'
        >>> clear_wizard_oauth_credentials()
    """
    _wizard_oauth_credentials.clear()
    cid = str(client_id or "").strip()
    sec = str(client_secret or "").strip()
    if cid and sec:
        _wizard_oauth_credentials["client_id"] = cid
        _wizard_oauth_credentials["client_secret"] = sec


def clear_wizard_oauth_credentials() -> None:
    """Drop in-memory wizard OAuth credentials (tests and wipe flows).

    Examples:
        >>> clear_wizard_oauth_credentials() is None
        True
    """
    _wizard_oauth_credentials.clear()


def oauth_client_credentials() -> tuple[str | None, str | None]:
    """Return OAuth app client id and secret from the wizard host environment.

    Returns:
        tuple[str | None, str | None]: ``(client_id, client_secret)``; either may be unset.

    Examples:
        >>> oauth_client_credentials()[0] is None or isinstance(oauth_client_credentials()[0], str)
        True
    """
    wiz_id = _wizard_oauth_credentials.get("client_id", "").strip()
    wiz_sec = _wizard_oauth_credentials.get("client_secret", "").strip()
    if wiz_id and wiz_sec:
        return wiz_id, wiz_sec
    client_id = os.environ.get("SEVN_GITHUB_OAUTH_CLIENT_ID", "").strip() or None
    client_secret = os.environ.get("SEVN_GITHUB_OAUTH_CLIENT_SECRET", "").strip() or None
    return client_id, client_secret


def oauth_configured() -> bool:
    """Return True when OAuth app credentials are available on the wizard host.

    Returns:
        bool: True when both ``SEVN_GITHUB_OAUTH_CLIENT_ID`` and ``SECRET`` are set.

    Examples:
        >>> oauth_configured() in (True, False)
        True
    """
    client_id, client_secret = oauth_client_credentials()
    return bool(client_id and client_secret)


def callback_redirect_uri(*, port: int) -> str:
    """Build the GitHub OAuth callback URL for the onboarding server port.

    Args:
        port (int): ``sevn onboard --web`` bind port (default 8844).

    Returns:
        str: ``http://127.0.0.1:{port}/api/github/oauth/callback``.

    Examples:
        >>> callback_redirect_uri(port=8844)
        'http://127.0.0.1:8844/api/github/oauth/callback'
    """
    return f"http://127.0.0.1:{port}/api/github/oauth/callback"


def _prune_oauth_states() -> None:
    """Drop expired OAuth state rows from the in-memory CSRF map.

    Examples:
        >>> from sevn.onboarding.github_oauth import _prune_oauth_states, mint_oauth_state
        >>> _ = mint_oauth_state()
        >>> _prune_oauth_states() is None
        True
    """
    now = time.monotonic()
    expired = [key for key, expiry in _oauth_states.items() if expiry < now]
    for key in expired:
        _oauth_states.pop(key, None)


def mint_oauth_state() -> str:
    """Mint a single-use CSRF ``state`` value for the OAuth authorize redirect.

    Returns:
        str: URL-safe random state stored until consumed or TTL expiry.

    Examples:
        >>> state = mint_oauth_state()
        >>> isinstance(state, str) and len(state) > 10
        True
    """
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = time.monotonic() + _STATE_TTL_SECONDS
    _prune_oauth_states()
    return state


def validate_oauth_state(state: str) -> bool:
    """Consume ``state`` when valid and unexpired (CSRF protection).

    Args:
        state (str): ``state`` query param from the OAuth callback.

    Returns:
        bool: True when the state was issued by this process and not yet used.

    Examples:
        >>> s = mint_oauth_state()
        >>> validate_oauth_state(s)
        True
        >>> validate_oauth_state(s)
        False
    """
    text = str(state).strip()
    if not text:
        return False
    expiry = _oauth_states.pop(text, None)
    if expiry is None:
        return False
    return time.monotonic() <= expiry


def clear_oauth_states() -> None:
    """Clear in-memory OAuth state (tests only).

    Examples:
        >>> clear_oauth_states() is None
        True
    """
    _oauth_states.clear()


def build_authorize_url(*, state: str, client_id: str, redirect_uri: str) -> str:
    """Build the GitHub OAuth authorize URL for the operator browser.

    Args:
        state (str): CSRF state from :func:`mint_oauth_state`.
        client_id (str): OAuth app client id.
        redirect_uri (str): Registered callback URL.

    Returns:
        str: Absolute authorize URL.

    Examples:
        >>> url = build_authorize_url(
        ...     state="abc",
        ...     client_id="cid",
        ...     redirect_uri="http://127.0.0.1:8844/api/github/oauth/callback",
        ... )
        >>> "github.com/login/oauth/authorize" in url
        True
    """
    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "repo read:user",
            "state": state,
        }
    )
    return f"https://github.com/login/oauth/authorize?{params}"


async def exchange_code_for_token(
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> str:
    """Exchange an OAuth authorization code for a GitHub access token.

    Args:
        code (str): Authorization code from the callback query string.
        client_id (str): OAuth app client id.
        client_secret (str): OAuth app client secret.
        redirect_uri (str): Callback URL used in the authorize step.

    Returns:
        str: GitHub access token (PAT-equivalent).

    Raises:
        ValueError: When GitHub returns an error or omits ``access_token``.

    Examples:
        >>> import asyncio
        >>> async def _demo():
        ...     try:
        ...         await exchange_code_for_token(
        ...             code="bad",
        ...             client_id="x",
        ...             client_secret="y",
        ...             redirect_uri="http://127.0.0.1:8844/api/github/oauth/callback",
        ...         )
        ...     except ValueError:
        ...         return True
        ...     return False
        >>> asyncio.run(_demo())
        True
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": str(code).strip(),
                "redirect_uri": redirect_uri,
            },
        )
    payload = resp.json()
    if not isinstance(payload, dict):
        msg = "GitHub token exchange returned non-object JSON"
        raise ValueError(msg)
    if payload.get("error"):
        desc = payload.get("error_description") or payload.get("error")
        raise ValueError(str(desc))
    token = payload.get("access_token")
    if not isinstance(token, str) or not token.strip():
        msg = "GitHub token exchange did not return access_token"
        raise ValueError(msg)
    return token.strip()


async def fetch_github_user(token: str) -> dict[str, Any]:
    """Call ``GET /user`` to validate a GitHub token and read the login name.

    Args:
        token (str): OAuth or PAT bearer token.

    Returns:
        dict[str, Any]: GitHub user JSON (includes ``login`` when successful).

    Raises:
        httpx.HTTPStatusError: When GitHub rejects the token.

    Examples:
        >>> import asyncio
        >>> async def _demo():
        ...     try:
        ...         await fetch_github_user("invalid-token")
        ...     except Exception:
        ...         return True
        ...     return False
        >>> asyncio.run(_demo())
        True
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token.strip()}",
        "X-GitHub-Api-Version": _GITHUB_API_VERSION,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get("https://api.github.com/user", headers=headers)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        msg = "GitHub /user returned non-object JSON"
        raise ValueError(msg)
    return data


__all__ = [
    "GITHUB_TOKEN_LOGICAL_KEY",
    "build_authorize_url",
    "callback_redirect_uri",
    "clear_oauth_states",
    "clear_wizard_oauth_credentials",
    "exchange_code_for_token",
    "fetch_github_user",
    "mint_oauth_state",
    "oauth_client_credentials",
    "oauth_configured",
    "set_wizard_oauth_credentials",
    "validate_oauth_state",
]
