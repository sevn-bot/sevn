"""Shared fixtures for Codex OAuth tests (``codex-oauth-subscription`` W1)."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from typing import Any

import pytest

from sevn.security.oauth.constants import CODEX_JWT_AUTH_CLAIM
from sevn.security.oauth.credential import CodexOAuthCredential


def b64url_json(data: dict[str, Any]) -> str:
    """Encode a dict as unpadded base64url JSON (JWT segment helper)."""
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def fake_access_jwt(*, account_id: str = "acct-test-123") -> str:
    """Build a minimal JWT-shaped access token with the Codex account claim."""
    header = b64url_json({"alg": "none", "typ": "JWT"})
    payload = b64url_json(
        {
            CODEX_JWT_AUTH_CLAIM: {"chatgpt_account_id": account_id},
            "exp": int(time.time()) + 3600,
        },
    )
    return f"{header}.{payload}.sig"


def s256_challenge(verifier: str) -> str:
    """Compute the S256 PKCE code challenge for a verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


@pytest.fixture
def sample_credential() -> CodexOAuthCredential:
    """Valid Codex OAuth credential blob for persistence/refresh tests."""
    return CodexOAuthCredential(
        access=fake_access_jwt(account_id="acct-fixture-99"),
        refresh="rt-fixture-abc",
        expires=int(time.time() * 1000) + 3_600_000,
        account_id="acct-fixture-99",
    )


@pytest.fixture
def expired_credential() -> CodexOAuthCredential:
    """Credential with access token already past ``expires`` (ms epoch)."""
    return CodexOAuthCredential(
        access=fake_access_jwt(account_id="acct-expired"),
        refresh="rt-expired-xyz",
        expires=int(time.time() * 1000) - 60_000,
        account_id="acct-expired",
    )


@pytest.fixture
def token_exchange_response() -> dict[str, Any]:
    """OpenAI token endpoint JSON (authorization_code / refresh_token grants)."""
    return {
        "access_token": fake_access_jwt(account_id="acct-from-token-endpoint"),
        "refresh_token": "rt-from-token-endpoint",
        "expires_in": 3600,
    }
