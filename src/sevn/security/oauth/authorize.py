"""Authorize-URL builder for Codex OAuth (W2).

Module: sevn.security.oauth.authorize
Depends: sevn.security.oauth.pkce, sevn.security.oauth.constants

Exports:
    AuthorizationFlow — PKCE/state/authorize URL bundle for the login handoff.
    build_authorization_flow — construct authorize URL with Codex-specific params.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse, urlunparse

from sevn.security.oauth.constants import (
    CODEX_OAUTH_AUTHORIZE_URL,
    CODEX_OAUTH_CLIENT_ID,
    CODEX_OAUTH_ORIGINATOR,
    CODEX_OAUTH_REDIRECT_URI,
    CODEX_OAUTH_SCOPE,
)
from sevn.security.oauth.pkce import PkcePair, generate_pkce_pair


@dataclass(frozen=True, slots=True)
class AuthorizationFlow:
    """OAuth authorization handoff state (PKCE + state + browser URL)."""

    pkce: PkcePair
    state: str
    authorize_url: str


def build_authorization_flow() -> AuthorizationFlow:
    """Build PKCE, state, and the Codex authorize URL (D5 local / headless entry).

    Returns:
        AuthorizationFlow: PKCE pair, CSRF state, and browser-openable URL.

    Examples:
        >>> flow = build_authorization_flow()
        >>> flow.authorize_url.startswith(CODEX_OAUTH_AUTHORIZE_URL)
        True
        >>> flow.state
        '...'
    """
    pkce = generate_pkce_pair()
    state = secrets.token_urlsafe(32)
    query = urlencode(
        {
            "client_id": CODEX_OAUTH_CLIENT_ID,
            "redirect_uri": CODEX_OAUTH_REDIRECT_URI,
            "scope": CODEX_OAUTH_SCOPE,
            "response_type": "code",
            "code_challenge": pkce.challenge,
            "code_challenge_method": "S256",
            "state": state,
            "id_token_add_organizations": "true",  # nosec B105 — OAuth query flag
            "codex_cli_simplified_flow": "true",  # nosec B105 — OAuth query flag
            "originator": CODEX_OAUTH_ORIGINATOR,
        },
    )
    parsed = urlparse(CODEX_OAUTH_AUTHORIZE_URL)
    authorize_url = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            query,
            parsed.fragment,
        ),
    )
    return AuthorizationFlow(pkce=pkce, state=state, authorize_url=authorize_url)
