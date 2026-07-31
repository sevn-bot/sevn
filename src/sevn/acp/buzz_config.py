"""Buzz identity resolution via secrets chain (#72, W31.4).

Module: sevn.acp.buzz_config
Depends: os, sevn.channels._common, sevn.security.secrets

Exports:
    BuzzIdentity — resolved relay URL + private key (never logged).
    resolve_buzz_identity — expand refs / env without plaintext ``sevn.json`` values.
    resolve_buzz_identity_sync — synchronous wrapper for skill scripts.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sevn.channels._common import channel_blob, platform_config_from_workspace
from sevn.security.secrets.cache import ResolvedSecretsCache
from sevn.security.secrets.chain import SecretsChain, get_secret_resilient
from sevn.security.secrets.errors import SecretUnresolvedError
from sevn.security.secrets.factory import secrets_chain_from_workspace
from sevn.security.secrets.value_expand import EnvUnresolvedError, expand_refs_env_then_secret

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

BUZZ_PRIVATE_KEY_LOGICAL = "buzz.private_key"
BUZZ_RELAY_URL_LOGICAL = "buzz.relay_url"
BUZZ_PRIVATE_KEY_ENV = "BUZZ_PRIVATE_KEY"
BUZZ_RELAY_URL_ENV = "BUZZ_RELAY_URL"
_SECRET_REF = re.compile(r"^\$\{SECRET:([^}]+)\}$")
_SECRETS_CACHE_TTL_SECONDS = 300


@dataclass(frozen=True, slots=True)
class BuzzIdentity:
    """Resolved Buzz relay credentials for adapter + skill tooling."""

    relay_url: str
    private_key: str


def _first_non_empty(*values: object) -> str:
    """Return the first non-blank string among ``values``.

    Args:
        values (object): Candidate values (variadic).

    Returns:
        str: First stripped non-empty string, or ``""``.

    Examples:
        >>> _first_non_empty("", "x", "y")
        'x'
    """
    for raw in values:
        text = str(raw or "").strip()
        if text:
            return text
    return ""


def _ref_from_blob(blob: dict[str, Any], *keys: str) -> str:
    """Return the first configured ref string from ``blob``.

    Args:
        blob (dict[str, Any]): Raw ``channels.buzz`` config dict.
        keys (str): Candidate field names in priority order (variadic).

    Returns:
        str: Ref string or ``""``.

    Examples:
        >>> _ref_from_blob({"private_key_ref": "x"}, "private_key_ref")
        'x'
    """
    for key in keys:
        raw = blob.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return ""


async def _resolve_ref(
    ref: str,
    chain: SecretsChain,
    cache: ResolvedSecretsCache,
) -> str | None:
    """Expand one credential reference via the workspace secrets chain.

    Args:
        ref (str): Literal or ``${SECRET:…}`` / ``${ENV:…}`` reference.
        chain (SecretsChain): Workspace secrets chain.
        cache (ResolvedSecretsCache): TTL cache for secret expansion.

    Returns:
        str | None: Resolved plaintext when available.

    Examples:
        >>> _resolve_ref.__name__
        '_resolve_ref'
    """
    stripped = ref.strip()
    if not stripped:
        return None
    if not stripped.startswith("${"):
        return stripped
    try:
        expanded = await expand_refs_env_then_secret(stripped, cache)
    except (EnvUnresolvedError, SecretUnresolvedError, ValueError):
        expanded = stripped
    else:
        expanded = expanded.strip()
        if expanded and "${SECRET:" not in expanded and "${ENV:" not in expanded:
            return expanded or None
    match = _SECRET_REF.match(stripped)
    if match is not None:
        inner = match.group(1)
        if ":" not in inner:
            value = await get_secret_resilient(chain, inner)
            if value:
                return value.strip() or None
    return None


async def resolve_buzz_identity(
    workspace: WorkspaceConfig,
    *,
    content_root: str | None = None,
) -> BuzzIdentity | None:
    """Resolve Buzz relay URL and private key without reading plaintext config.

    Precedence:
    1. ``channels.buzz.private_key_ref`` / ``relay_url_ref`` via secrets chain
    2. ``${ENV:BUZZ_PRIVATE_KEY}`` / ``${ENV:BUZZ_RELAY_URL}`` expansion
    3. Process env ``BUZZ_PRIVATE_KEY`` / ``BUZZ_RELAY_URL`` (operator export)

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.
        content_root (str | None): Content root for secrets chain lookup.

    Returns:
        BuzzIdentity | None: Resolved identity or ``None`` when incomplete.

    Examples:
        >>> import asyncio
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> asyncio.run(resolve_buzz_identity(WorkspaceConfig.minimal())) is None
        True
    """
    blob = channel_blob(workspace, "buzz")
    cfg = platform_config_from_workspace(workspace, "buzz")
    key_ref = (
        _ref_from_blob(
            blob,
            "private_key_ref",
            "buzz_private_key_ref",
            "bot_token_ref",
        )
        or str(cfg.bot_token_ref or "").strip()
    )
    url_ref = (
        _ref_from_blob(blob, "relay_url_ref", "buzz_relay_url_ref", "webhook_secret_ref")
        or str(cfg.webhook_secret_ref or "").strip()
    )

    private_key = ""
    relay_url = ""

    if content_root:
        from pathlib import Path

        chain = secrets_chain_from_workspace(Path(content_root), workspace.secrets_backend)
        cache = ResolvedSecretsCache(chain, ttl_seconds=_SECRETS_CACHE_TTL_SECONDS)
        if key_ref:
            private_key = _first_non_empty(await _resolve_ref(key_ref, chain, cache))
        if url_ref:
            relay_url = _first_non_empty(await _resolve_ref(url_ref, chain, cache))
        if not private_key:
            private_key = _first_non_empty(
                await get_secret_resilient(chain, BUZZ_PRIVATE_KEY_LOGICAL)
            )
        if not relay_url:
            relay_url = _first_non_empty(await get_secret_resilient(chain, BUZZ_RELAY_URL_LOGICAL))

    private_key = _first_non_empty(private_key, os.environ.get(BUZZ_PRIVATE_KEY_ENV))
    relay_url = _first_non_empty(relay_url, os.environ.get(BUZZ_RELAY_URL_ENV))
    if not relay_url or not private_key:
        return None
    return BuzzIdentity(relay_url=relay_url.rstrip("/"), private_key=private_key)


def resolve_buzz_identity_sync(
    workspace: WorkspaceConfig,
    *,
    content_root: str | None = None,
) -> BuzzIdentity | None:
    """Synchronous wrapper for :func:`resolve_buzz_identity`.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.
        content_root (str | None): Content root for secrets chain lookup.

    Returns:
        BuzzIdentity | None: Resolved identity or ``None`` when incomplete.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> resolve_buzz_identity_sync(WorkspaceConfig.minimal()) is None
        True
    """
    import asyncio

    return asyncio.run(resolve_buzz_identity(workspace, content_root=content_root))


__all__ = [
    "BUZZ_PRIVATE_KEY_LOGICAL",
    "BUZZ_RELAY_URL_LOGICAL",
    "BuzzIdentity",
    "resolve_buzz_identity",
    "resolve_buzz_identity_sync",
]
