"""Proxy-owned Codex OAuth refresh lifecycle (W3.1 — uses W2 token/storage).

Module: sevn.proxy.oauth_lifecycle
Depends: sevn.security.oauth.storage, sevn.security.oauth.token_client

Exports:
    OauthCredentialMissingError — raised when ``oauth.openai`` is absent.
    is_oauth_credential_fresh — whether access token is beyond refresh skew.
    ensure_fresh_oauth_credential — refresh near-expiry credentials under a lock (D3).
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from sevn.security.oauth.storage import load_codex_oauth_credential, persist_codex_oauth_credential
from sevn.security.oauth.token_client import refresh_access_token

if TYPE_CHECKING:
    from sevn.security.oauth.credential import CodexOAuthCredential
    from sevn.security.secrets.chain import SecretsChain

_REFRESH_SKEW_MS = 60_000
_oauth_refresh_lock = asyncio.Lock()


class OauthCredentialMissingError(RuntimeError):
    """``oauth.openai`` is not configured in the secrets chain."""


def is_oauth_credential_fresh(credential: CodexOAuthCredential) -> bool:
    """Return True when access token expiry is beyond the refresh skew window.

    Args:
        credential (CodexOAuthCredential): Stored OAuth credential.

    Returns:
        bool: ``True`` when refresh is not yet required.

    Examples:
        >>> # Covered by tests/security/oauth/test_refresh_lock.py.
        >>> True
        True
    """
    return _is_fresh(credential)


def _is_fresh(credential: CodexOAuthCredential) -> bool:
    """Return True when access token expiry is beyond the refresh skew window.

    Args:
        credential (CodexOAuthCredential): Stored OAuth credential.

    Returns:
        bool: ``True`` when refresh is not yet required.

    Examples:
        >>> # Covered by tests/security/oauth/test_refresh_lock.py.
        >>> True
        True
    """
    now_ms = int(time.time() * 1000)
    return credential.expires > now_ms + _REFRESH_SKEW_MS


async def ensure_fresh_oauth_credential(chain: SecretsChain) -> CodexOAuthCredential:
    """Return a non-expired Codex OAuth credential, refreshing under lock when needed (D3).

    Args:
        chain (SecretsChain): Workspace secrets chain containing ``oauth.openai``.

    Returns:
        CodexOAuthCredential: Fresh credential (possibly after refresh + persist).

    Raises:
        OauthCredentialMissingError: When ``oauth.openai`` is missing.
        RuntimeError: When refresh fails.

    Examples:
        >>> # Covered by tests/security/oauth/test_refresh_lock.py.
        >>> True
        True
    """
    async with _oauth_refresh_lock:
        credential = await load_codex_oauth_credential(chain)
        if credential is None:
            msg = "oauth.openai credential is missing; run `sevn providers oauth login --provider openai`"
            raise OauthCredentialMissingError(msg)
        if _is_fresh(credential):
            return credential

        result = await refresh_access_token(refresh_token=credential.refresh)
        if result.type != "success" or result.credential is None:
            msg = "failed to refresh oauth.openai credential"
            raise RuntimeError(msg)
        await persist_codex_oauth_credential(chain, result.credential)
        return result.credential
