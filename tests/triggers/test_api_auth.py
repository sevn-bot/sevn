"""Triggers API bearer auth (`specs/30-non-interactive-triggers.md` §11)."""

from __future__ import annotations

from sevn.gateway.auth import mint_webchat_jwt
from sevn.triggers.auth import (
    TRIGGERS_API_OPENAPI_BEARER_SCOPES,
    triggers_api_auth_required,
    verify_triggers_api_bearer,
)


def test_openapi_scopes_match_webchat_jwt() -> None:
    """OpenAPI documents webchat JWT scopes — no separate OAuth machinery."""
    assert TRIGGERS_API_OPENAPI_BEARER_SCOPES == ("session:read", "session:write")


def test_auth_disabled_when_no_secrets() -> None:
    """Dev laptops without tokens skip bearer enforcement."""
    assert triggers_api_auth_required(gateway_token=None, webchat_jwt_secret=None) is False
    assert (
        verify_triggers_api_bearer(
            authorization_header=None,
            gateway_token=None,
            webchat_jwt_secret=None,
        )
        is True
    )


def test_gateway_bearer_accepted() -> None:
    """Configured gateway token accepts matching bearer."""
    assert (
        verify_triggers_api_bearer(
            authorization_header="Bearer secret",
            gateway_token="secret",
            webchat_jwt_secret=None,
        )
        is True
    )
    assert (
        verify_triggers_api_bearer(
            authorization_header="Bearer wrong",
            gateway_token="secret",
            webchat_jwt_secret=None,
        )
        is False
    )


def test_webchat_jwt_accepted_with_session_scopes() -> None:
    """Webchat JWT with session scopes authorizes triggers API."""
    token, _ = mint_webchat_jwt(secret="jwt-secret", sub="owner", ttl_seconds=3600)
    assert (
        verify_triggers_api_bearer(
            authorization_header=f"Bearer {token}",
            gateway_token=None,
            webchat_jwt_secret="jwt-secret",
        )
        is True
    )
