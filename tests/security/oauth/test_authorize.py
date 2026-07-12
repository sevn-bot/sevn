"""Authorize-URL construction tests (W1.1 — ``codex-oauth-subscription`` plan)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from tests.security.oauth.conftest import s256_challenge

from sevn.security.oauth.authorize import AuthorizationFlow, build_authorization_flow
from sevn.security.oauth.constants import (
    CODEX_OAUTH_AUTHORIZE_URL,
    CODEX_OAUTH_CLIENT_ID,
    CODEX_OAUTH_ORIGINATOR,
    CODEX_OAUTH_REDIRECT_URI,
    CODEX_OAUTH_SCOPE,
)
from sevn.security.oauth.pkce import PkcePair


def test_authorization_flow_dataclass_fields() -> None:
    """``AuthorizationFlow`` bundles PKCE, state, and authorize URL."""
    pkce = PkcePair(verifier="verifier-abc", challenge="challenge-xyz")
    flow = AuthorizationFlow(pkce=pkce, state="csrf-state", authorize_url="https://example.test")
    assert flow.pkce is pkce
    assert flow.state == "csrf-state"
    assert flow.authorize_url.startswith("https://")


def test_build_authorization_flow_url_targets_openai_authorize() -> None:
    """Authorize URL uses the locked Codex authorize endpoint."""
    flow = build_authorization_flow()
    parsed = urlparse(flow.authorize_url)
    assert parsed.scheme == "https"
    assert flow.authorize_url.startswith(CODEX_OAUTH_AUTHORIZE_URL)


def test_build_authorization_flow_includes_pkce_s256_params() -> None:
    """URL carries S256 ``code_challenge`` matching the embedded verifier."""
    flow = build_authorization_flow()
    params = parse_qs(urlparse(flow.authorize_url).query)
    assert params["code_challenge_method"] == ["S256"]
    challenge = params["code_challenge"][0]
    assert challenge == s256_challenge(flow.pkce.verifier)
    assert challenge == flow.pkce.challenge


def test_build_authorization_flow_includes_locked_client_and_redirect() -> None:
    """Client id, redirect URI, and scope match W0 constants."""
    flow = build_authorization_flow()
    params = parse_qs(urlparse(flow.authorize_url).query)
    assert params["client_id"] == [CODEX_OAUTH_CLIENT_ID]
    assert params["redirect_uri"] == [CODEX_OAUTH_REDIRECT_URI]
    assert params["scope"] == [CODEX_OAUTH_SCOPE]
    assert params["response_type"] == ["code"]


def test_build_authorization_flow_includes_codex_extra_params() -> None:
    """Codex-specific authorize query params from the reference plugin."""
    flow = build_authorization_flow()
    params = parse_qs(urlparse(flow.authorize_url).query)
    assert params["id_token_add_organizations"] == ["true"]
    assert params["codex_cli_simplified_flow"] == ["true"]
    assert params["originator"] == [CODEX_OAUTH_ORIGINATOR]


def test_build_authorization_flow_state_is_non_empty_and_unique() -> None:
    """CSRF ``state`` is present and differs across flows."""
    a = build_authorization_flow()
    b = build_authorization_flow()
    assert a.state
    assert b.state
    assert a.state != b.state
    params = parse_qs(urlparse(a.authorize_url).query)
    assert params["state"] == [a.state]
