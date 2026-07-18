"""Resolve ``skills.discogs`` credential refs into subprocess env vars.

Module: sevn.skills.discogs_secrets
Depends: re, sevn.config.sections.skills_discogs, sevn.security.secrets

Exports:
    merge_discogs_proc_env — inject Discogs auth settings into skill subprocess env.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from sevn.config.sections.skills_discogs import discogs_settings
from sevn.config.workspace_config import WorkspaceConfig
from sevn.security.secrets.cache import ResolvedSecretsCache
from sevn.security.secrets.chain import SecretsChain, get_secret_resilient
from sevn.security.secrets.errors import SecretUnresolvedError
from sevn.security.secrets.factory import secrets_chain_from_workspace
from sevn.security.secrets.value_expand import EnvUnresolvedError, expand_refs_env_then_secret

_SECRET_REF = re.compile(r"^\$\{SECRET:([^}]+)\}$")
_SECRETS_CACHE_TTL_SECONDS = 300

_DISCOGS_USER_AGENT_ENV: Final[str] = "DISCOGS_USER_AGENT"
_DISCOGS_AUTH_METHOD_ENV: Final[str] = "DISCOGS_AUTH_METHOD"
_DISCOGS_CONFIRM_WRITES_ENV: Final[str] = "DISCOGS_CONFIRM_WRITES"
_DISCOGS_USER_TOKEN_ENV: Final[str] = "DISCOGS_USER_TOKEN"
_DISCOGS_CONSUMER_KEY_ENV: Final[str] = "DISCOGS_CONSUMER_KEY"
_DISCOGS_CONSUMER_SECRET_ENV: Final[str] = "DISCOGS_CONSUMER_SECRET"
_DISCOGS_OAUTH_TOKEN_ENV: Final[str] = "DISCOGS_OAUTH_TOKEN"
_DISCOGS_OAUTH_TOKEN_SECRET_ENV: Final[str] = "DISCOGS_OAUTH_TOKEN_SECRET"


async def _resolve_credential_ref(
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
        >>> _resolve_credential_ref.__name__
        '_resolve_credential_ref'
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
                text = value.strip()
                return text or None
    return None


async def merge_discogs_proc_env(
    env: dict[str, str],
    *,
    content_root: Path,
    cfg: WorkspaceConfig | None,
) -> None:
    """Inject Discogs auth env vars from sevn config and secrets.

    Resolved values are applied with ``setdefault`` so explicit operator env wins.

    Args:
        env (dict[str, str]): Mutable subprocess environment (updated in place).
        content_root (Path): Workspace content root for secrets chain resolution.
        cfg (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        None

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(merge_discogs_proc_env)
        True
    """
    settings = discogs_settings(cfg)
    if cfg is None or not settings.enabled:
        return

    env.setdefault(_DISCOGS_USER_AGENT_ENV, settings.user_agent)
    env.setdefault(_DISCOGS_AUTH_METHOD_ENV, settings.auth_method)
    env.setdefault(
        _DISCOGS_CONFIRM_WRITES_ENV,
        "true" if settings.confirm_writes else "false",
    )

    chain = secrets_chain_from_workspace(content_root, cfg.secrets_backend if cfg else None)
    cache = ResolvedSecretsCache(chain, ttl_seconds=_SECRETS_CACHE_TTL_SECONDS)

    ref_map = {
        _DISCOGS_USER_TOKEN_ENV: settings.user_token,
        _DISCOGS_CONSUMER_KEY_ENV: settings.consumer_key,
        _DISCOGS_CONSUMER_SECRET_ENV: settings.consumer_secret,
        _DISCOGS_OAUTH_TOKEN_ENV: settings.oauth_token,
        _DISCOGS_OAUTH_TOKEN_SECRET_ENV: settings.oauth_token_secret,
    }
    for env_key, ref in ref_map.items():
        if not isinstance(ref, str) or not ref.strip():
            continue
        resolved = await _resolve_credential_ref(ref, chain, cache)
        if resolved:
            env.setdefault(env_key, resolved)
