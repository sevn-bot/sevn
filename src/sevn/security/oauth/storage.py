"""Persist Codex OAuth credentials via the secrets chain (W2, D2).

Module: sevn.security.oauth.storage
Depends: sevn.security.oauth.credential, sevn.security.secrets.chain

Exports:
    persist_codex_oauth_credential — write credential JSON to ``oauth.openai``.
    load_codex_oauth_credential — read and parse credential from the chain.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sevn.security.oauth.credential import CodexOAuthCredential, oauth_openai_secret_alias

if TYPE_CHECKING:
    from sevn.security.secrets.chain import SecretsChain


async def persist_codex_oauth_credential(
    chain: SecretsChain,
    credential: CodexOAuthCredential,
) -> None:
    """Persist a Codex OAuth credential blob at ``oauth.openai`` (D2).

    Args:
        chain (SecretsChain): Workspace secrets chain.
        credential (CodexOAuthCredential): Credential to store.

    Examples:
        >>> # Covered by tests/security/oauth/test_credential_store.py.
        >>> True
        True
    """
    await chain.set(oauth_openai_secret_alias(), credential.model_dump_json())


async def load_codex_oauth_credential(chain: SecretsChain) -> CodexOAuthCredential | None:
    """Load the Codex OAuth credential from ``oauth.openai`` when present.

    Args:
        chain (SecretsChain): Workspace secrets chain.

    Returns:
        CodexOAuthCredential | None: Parsed credential, or ``None`` when missing.

    Raises:
        ValueError: When stored JSON is corrupt or fails validation.
        json.JSONDecodeError: When stored JSON cannot be parsed.

    Examples:
        >>> # Covered by tests/security/oauth/test_credential_store.py.
        >>> True
        True
    """
    raw = await chain.get(oauth_openai_secret_alias())
    if raw is None:
        return None
    try:
        return CodexOAuthCredential.model_validate_json(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        msg = f"invalid oauth credential JSON at {oauth_openai_secret_alias()!r}"
        raise ValueError(msg) from exc
