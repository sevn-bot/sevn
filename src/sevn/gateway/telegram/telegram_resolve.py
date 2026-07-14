"""Resolve Telegram bot token via env + secrets chain (``specs/06-secrets.md`` §2.5, §4).

Module: sevn.gateway.telegram.telegram_resolve
Depends: pathlib, re, sevn.security.secrets.{cache,factory,value_expand}, sevn.security.secrets.errors

Exports:
    resolve_telegram_bot_token — expand ``bot_token_ref`` (${ENV}, ${SECRET}), chain lookup.

v1 uses **operator env injection**: ``channels.telegram.bot_token_ref`` prefers
``${ENV:…}`` (for example ``${ENV:SEVN_TELEGRAM_BOT_TOKEN}``) or a plaintext logical key resolved
against ``secrets_backend``. There is no authenticated runtime gateway POST that injects the token.
"""

from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

from sevn.config.workspace_config import WorkspaceConfig
from sevn.security.secrets.cache import ResolvedSecretsCache
from sevn.security.secrets.chain import SecretsChain, get_secret_resilient
from sevn.security.secrets.errors import (
    SecretsStoreCorruptError,
    SecretUnresolvedError,
    is_encrypted_store_decrypt_failure,
)
from sevn.security.secrets.factory import (
    resolve_primary_encrypted_store_path,
    secrets_chain_from_workspace,
)
from sevn.security.secrets.value_expand import (
    EnvUnresolvedError,
    expand_env_refs,
    expand_refs_env_then_secret,
)

_TG_BOT_TOKEN_RE = re.compile(r"^[0-9]+:[A-Za-z0-9_-]+\s*$")
_ENV_REF_RE = re.compile(r"^\$\{ENV:([^}]+)\}$")


async def _resolve_env_ref_from_chain(
    chain: SecretsChain,
    ref_raw: str,
) -> str | None:
    """Resolve ``${ENV:LOGICAL_KEY}`` via the secrets chain when process env is unset.

    Args:
        chain (SecretsChain): Workspace secrets chain.
        ref_raw (str): Raw ``bot_token_ref`` value from ``sevn.json``.

    Returns:
        str | None: Token text when the logical key resolves to a Bot API token shape.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.security.secrets.factory import secrets_chain_from_workspace
        >>> chain = secrets_chain_from_workspace(Path("/tmp"), None)
        >>> asyncio.run(_resolve_env_ref_from_chain(chain, "${ENV:MISSING}")) is None
        True
    """
    match = _ENV_REF_RE.match(ref_raw.strip())
    if match is None:
        return None
    logical_key = match.group(1).strip()
    if not logical_key:
        return None
    value = await get_secret_resilient(chain, logical_key)
    if not value:
        return None
    text = value.strip()
    if _TG_BOT_TOKEN_RE.match(text):
        return text
    return None


async def resolve_telegram_bot_token(
    workspace: WorkspaceConfig,
    *,
    content_root: Path,
) -> str | None:
    """Return the bot token for ``channels.telegram``.

    Applies ``expand_env_refs(..., strict=False)`` then, when ``${SECRET:…}`` spans remain,
    iterated env-then-secret expansion against the workspace secrets chain. Bot API tokens shaped
    as ``<id>:<secret>`` are returned without a chain lookup once fully expanded.

    Args:
        workspace (WorkspaceConfig): Parsed ``sevn.json``.
        content_root (Path): Workspace content root for encrypted-file backends.

    Returns:
        str | None: Token text when resolved; ``None`` when unset, unresolved ``${ENV:…}``, or when
            secret placeholders cannot expand.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import parse_workspace_config
        >>> ws = parse_workspace_config({"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}})
        >>> asyncio.run(resolve_telegram_bot_token(ws, content_root=Path("."))) is None
        True
    """

    ch = workspace.channels
    ref_raw: str | None = None
    if ch is not None and ch.telegram is not None and ch.telegram.bot_token_ref:
        ref_raw = str(ch.telegram.bot_token_ref).strip()
    if not ref_raw:
        return None

    chain = secrets_chain_from_workspace(content_root, workspace.secrets_backend)
    try:
        return await _resolve_against_chain(chain, ref_raw)
    except SecretsStoreCorruptError as exc:
        if is_encrypted_store_decrypt_failure(exc):
            from sevn.config.workspace_config import effective_encrypted_file_key_source
            from sevn.security.secrets.passphrase_prime import reconcile_unlock_env_with_keychain

            key_source = effective_encrypted_file_key_source(workspace.secrets_backend)
            if await reconcile_unlock_env_with_keychain(key_source=key_source):
                logger.warning(
                    "telegram_bot_token_retry_after_unlock_reconcile store={}",
                    resolve_primary_encrypted_store_path(content_root, workspace.secrets_backend),
                )
                try:
                    return await _resolve_against_chain(chain, ref_raw)
                except SecretsStoreCorruptError:
                    pass
            store_path = resolve_primary_encrypted_store_path(
                content_root, workspace.secrets_backend
            )
            logger.error(
                "telegram_bot_token_unresolved_store_decrypt_failed store={} reason={} "
                "(check SEVN_SECRETS_PASSPHRASE / remove a stale SEVN_SECRETS_MASTER_KEY)",
                store_path,
                exc,
            )
            return None
        raise


async def _resolve_against_chain(chain: SecretsChain, ref_raw: str) -> str | None:
    """Expand ``ref_raw`` (``${ENV:…}`` / ``${SECRET:…}``) against ``chain``.

    Split from :func:`resolve_telegram_bot_token` so that a ``SecretsStoreCorruptError`` from any
    chain read can be caught once by the caller and surfaced loudly.

    Args:
        chain (SecretsChain): Workspace secrets chain.
        ref_raw (str): Raw ``bot_token_ref`` value from ``sevn.json``.

    Returns:
        str | None: Resolved token, or ``None`` when unset / unresolved placeholders remain.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> from sevn.security.secrets.factory import secrets_chain_from_workspace
        >>> chain = secrets_chain_from_workspace(Path("/tmp"), None)
        >>> asyncio.run(_resolve_against_chain(chain, "${ENV:MISSING_TG}")) is None
        True
    """
    interim = expand_env_refs(ref_raw, strict=False)
    if "${ENV:" in interim:
        from_chain = await _resolve_env_ref_from_chain(chain, ref_raw)
        if from_chain:
            return from_chain
        return None

    interim_s = interim.strip()
    expanded = interim_s
    if "${SECRET:" in interim_s:
        cache = ResolvedSecretsCache(chain, ttl_seconds=0)
        try:
            expanded = await expand_refs_env_then_secret(interim_s, cache)
        except (EnvUnresolvedError, SecretUnresolvedError, ValueError):
            return None

    expanded = expanded.strip()
    if "${SECRET:" in expanded or "${ENV:" in expanded:
        return None

    if _TG_BOT_TOKEN_RE.match(expanded):
        return expanded

    return await get_secret_resilient(chain, expanded)
