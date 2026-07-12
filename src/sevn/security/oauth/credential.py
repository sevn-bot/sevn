"""Codex OAuth credential model and secret-alias helpers (W0 scaffold).

Module: sevn.security.oauth.credential
Depends: pydantic, sevn.security.oauth.constants

Exports:
    CodexOAuthCredential — stored credential shape at ``oauth.openai`` (D2).
    oauth_openai_secret_alias — canonical secret alias for OpenAI Codex OAuth.
    resolution_probe_credential — synthetic credential for pytest resolution tests.

Shape (D2): ``{access, refresh, expires, account_id}`` where ``expires`` is epoch
milliseconds and ``account_id`` is extracted from the access-token JWT claim
``https://api.openai.com/auth.chatgpt_account_id`` (fail if absent — W2).
"""

from __future__ import annotations

import base64
import json
import sys
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sevn.security.oauth.constants import CODEX_JWT_AUTH_CLAIM, OAUTH_OPENAI_SECRET_ALIAS


class CodexOAuthCredential(BaseModel):
    """OAuth credential blob persisted at ``oauth.openai`` (D2)."""

    model_config = ConfigDict(extra="forbid")

    access: str = Field(description="OAuth access token (JWT).")
    refresh: str = Field(description="OAuth refresh token.")
    expires: int = Field(description="Access-token expiry as Unix epoch milliseconds.")
    account_id: str = Field(description="ChatGPT account id from access-token JWT claim.")


def _b64url_json(data: dict[str, Any]) -> str:
    """Encode a dict as unpadded base64url JSON (JWT segment helper).

    Args:
        data (dict[str, Any]): JSON-serializable payload.

    Returns:
        str: Base64url-encoded JSON without padding.

    Examples:
        >>> _b64url_json({"a": 1}).endswith("=") is False
        True
    """
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def resolution_probe_credential() -> CodexOAuthCredential:
    """Return a synthetic credential for auth_mode resolution unit tests (pytest only).

    Returns:
        CodexOAuthCredential: Non-expired probe credential with a valid JWT shape.

    Raises:
        RuntimeError: When called outside the pytest suite.

    Examples:
        >>> import pytest  # doctest: +SKIP
        >>> resolution_probe_credential().account_id  # doctest: +SKIP
        'acct-resolution-probe'
    """
    if "pytest" not in sys.modules:
        msg = "resolution_probe_credential is for pytest resolution tests only"
        raise RuntimeError(msg)
    account_id = "acct-resolution-probe"
    payload = {
        CODEX_JWT_AUTH_CLAIM: {"chatgpt_account_id": account_id},
        "exp": int(time.time()) + 3600,
    }
    access = f"{_b64url_json({'alg': 'none', 'typ': 'JWT'})}.{_b64url_json(payload)}.sig"
    return CodexOAuthCredential(
        access=access,
        refresh="rt-probe",
        expires=int(time.time() * 1000) + 3_600_000,
        account_id=account_id,
    )


def oauth_openai_secret_alias() -> str:
    """Return the secrets-chain alias for OpenAI Codex OAuth credentials (D2).

    Returns:
        str: Always ``oauth.openai``.

    Examples:
        >>> oauth_openai_secret_alias()
        'oauth.openai'
    """
    return OAUTH_OPENAI_SECRET_ALIAS
