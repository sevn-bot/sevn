"""Gateway bearer token constants, generation, and secret-ref resolution.

Module: sevn.gateway.gateway_token
Depends: secrets, pathlib, sevn.config.settings, sevn.security.secrets.*

Constants:
    GATEWAY_TOKEN_LOGICAL_KEY — secrets chain logical id.
    GATEWAY_TOKEN_CONFIG_REF — default ``gateway.token`` placeholder in ``sevn.json``.
    GATEWAY_TOKEN_MIN_CHARS — minimum accepted plaintext length.

Exports:
    generate_gateway_token — CSPRNG hex token (64 chars).
    validate_gateway_token_plaintext — reject empty/short values.
    resolve_config_ref — expand env + ``${SECRET:…}`` refs to plaintext.
    resolve_gateway_token_ref — resolve ``gateway.token`` (env overrides config ref).
"""

from __future__ import annotations

import re
import secrets
from typing import TYPE_CHECKING

from loguru import logger

from sevn.config.settings import ProcessSettings
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

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.config.workspace_config import WorkspaceConfig

GATEWAY_TOKEN_LOGICAL_KEY: str = "sevn.gateway.token"
GATEWAY_TOKEN_CONFIG_REF: str = "${SECRET:keychain:sevn.gateway.token}"
GATEWAY_TOKEN_MIN_CHARS: int = 32
GATEWAY_TOKEN_HEX_LEN: int = 64

_ENV_REF_RE = re.compile(r"^\$\{ENV:([^}]+)\}$")


def generate_gateway_token() -> str:
    """Return a new gateway bearer token (64 lowercase hex chars).

    Returns:
        str: 256-bit token (`openssl rand -hex 32` equivalent).

    Examples:
        >>> t = generate_gateway_token()
        >>> len(t) == GATEWAY_TOKEN_HEX_LEN
        True
        >>> all(c in "0123456789abcdef" for c in t)
        True
    """
    return secrets.token_hex(32)


def validate_gateway_token_plaintext(value: str) -> str:
    """Validate operator-supplied gateway token plaintext.

    Args:
        value (str): Candidate token.

    Returns:
        str: Stripped plaintext.

    Raises:
        ValueError: When empty or shorter than ``GATEWAY_TOKEN_MIN_CHARS``.

    Examples:
        >>> validate_gateway_token_plaintext("x" * 32) == "x" * 32
        True
        >>> import pytest
        >>> with pytest.raises(ValueError, match="at least"):
        ...     validate_gateway_token_plaintext("short")
    """
    text = value.strip()
    if not text:
        msg = "gateway token must be non-empty"
        raise ValueError(msg)
    if len(text) < GATEWAY_TOKEN_MIN_CHARS:
        msg = (
            f"gateway token must be at least {GATEWAY_TOKEN_MIN_CHARS} characters "
            f"({GATEWAY_TOKEN_HEX_LEN} hex chars recommended; "
            "generate with: openssl rand -hex 32)"
        )
        raise ValueError(msg)
    return text


async def _resolve_env_ref_from_chain(chain: SecretsChain, ref_raw: str) -> str | None:
    """Resolve ``${ENV:LOGICAL_KEY}`` via the secrets chain when process env is unset.

    Surprising-but-intentional semantics: a ``${ENV:KEY}`` ref whose env var is unset
    falls back to looking ``KEY`` up in the secrets chain, so an operator may store the
    bearer either in the environment or the encrypted store under the same logical id.

    Args:
        chain (SecretsChain): Workspace secrets chain.
        ref_raw (str): Config ref (expected ``${ENV:…}`` form).

    Returns:
        str | None: Resolved plaintext, or ``None`` when not an env ref / missing.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_resolve_env_ref_from_chain)
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
    return text or None


async def _resolve_against_chain(
    chain: SecretsChain,
    ref_raw: str,
    *,
    unresolved_log_label: str = "config_ref_unresolved",
) -> str | None:
    """Expand ``ref_raw`` against ``chain`` to plaintext.

    Args:
        chain (SecretsChain): Workspace secrets chain.
        ref_raw (str): Config value (literal or ``${…}`` ref).
        unresolved_log_label (str): Log label when expansion leaves bracketed refs.

    Returns:
        str | None: Plaintext when fully resolved.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_resolve_against_chain)
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
    # An unresolved ``${SECRET:…}``/``${ENV:…}`` token (including mixed content such as
    # ``prefix-${SECRET:X}`` that could not be fully expanded) means the bearer is not
    # available; log which ref failed so the boot ``RuntimeError`` is not silent (M4).
    if "${SECRET:" in expanded or "${ENV:" in expanded:
        logger.warning("{} ref={}", unresolved_log_label, ref_raw)
        return None

    if expanded and "${" not in expanded:
        return expanded

    # Remaining case: a still-bracketed but non-SECRET/ENV ``${…}`` string (malformed).
    # Treat the whole literal as a logical secret-chain key as a last resort rather than
    # forwarding obviously-broken placeholder text as the bearer.
    value = await get_secret_resilient(chain, expanded)
    if not value:
        logger.warning("{} ref={}", unresolved_log_label, ref_raw)
        return None
    text = value.strip()
    return text or None


async def resolve_config_ref(
    workspace: WorkspaceConfig,
    *,
    content_root: Path,
    ref_raw: str | None,
    process: ProcessSettings | None = None,
    process_env_override: str | None = None,
    unresolved_log_label: str = "config_ref_unresolved",
) -> str | None:
    """Resolve a config value that may be plaintext or ``${ENV:…}`` / ``${SECRET:…}`` refs.

    Args:
        workspace (WorkspaceConfig): Parsed ``sevn.json``.
        content_root (Path): Workspace content root for encrypted-file backends.
        ref_raw (str | None): Config field value.
        process (ProcessSettings | None): Process env; default fresh settings.
        process_env_override (str | None): Optional env override checked before ``ref_raw``.
        unresolved_log_label (str): Log label when expansion leaves bracketed refs.

    Returns:
        str | None: Resolved plaintext when available.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import GatewayConfig, WorkspaceConfig
        >>> ws = WorkspaceConfig(
        ...     schema_version=1,
        ...     gateway=GatewayConfig(token="plain-token-value-at-least-32-chars-long"),
        ... )
        >>> asyncio.run(
        ...     resolve_config_ref(ws, content_root=Path("."), ref_raw=ws.gateway.token),
        ... ) == "plain-token-value-at-least-32-chars-long"
        True
    """
    _ = process  # reserved for future env-backed overrides beyond gateway token
    env_override = (process_env_override or "").strip()
    if env_override:
        return env_override

    if not ref_raw:
        return None

    text = str(ref_raw).strip()
    if not text:
        return None

    if "${" not in text:
        return text

    chain = secrets_chain_from_workspace(content_root, workspace.secrets_backend)
    try:
        return await _resolve_against_chain(chain, text, unresolved_log_label=unresolved_log_label)
    except SecretsStoreCorruptError as exc:
        if is_encrypted_store_decrypt_failure(exc):
            from sevn.config.workspace_config import effective_encrypted_file_key_source
            from sevn.security.secrets.passphrase_prime import reconcile_unlock_env_with_keychain

            key_source = effective_encrypted_file_key_source(workspace.secrets_backend)
            if await reconcile_unlock_env_with_keychain(key_source=key_source):
                logger.warning(
                    "config_ref_retry_after_unlock_reconcile label={} store={}",
                    unresolved_log_label,
                    resolve_primary_encrypted_store_path(content_root, workspace.secrets_backend),
                )
                try:
                    retry_chain = secrets_chain_from_workspace(
                        content_root, workspace.secrets_backend
                    )
                    return await _resolve_against_chain(
                        retry_chain,
                        text,
                        unresolved_log_label=unresolved_log_label,
                    )
                except SecretsStoreCorruptError:
                    pass
            store_path = resolve_primary_encrypted_store_path(
                content_root, workspace.secrets_backend
            )
            logger.error(
                "config_ref_unresolved_store_decrypt_failed label={} store={} reason={}",
                unresolved_log_label,
                store_path,
                exc,
            )
            return None
        raise


async def resolve_gateway_token_ref(
    workspace: WorkspaceConfig,
    *,
    content_root: Path,
    process: ProcessSettings | None = None,
) -> str | None:
    """Resolve effective gateway bearer token (env overrides config ref).

    Args:
        workspace (WorkspaceConfig): Parsed ``sevn.json``.
        content_root (Path): Workspace content root for encrypted-file backends.
        process (ProcessSettings | None): Process env; default fresh settings.

    Returns:
        str | None: Bearer token when resolved.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import GatewayConfig, WorkspaceConfig
        >>> ws = WorkspaceConfig(
        ...     schema_version=1,
        ...     gateway=GatewayConfig(token="plain-token-value-at-least-32-chars-long"),
        ... )
        >>> asyncio.run(
        ...     resolve_gateway_token_ref(ws, content_root=Path(".")),
        ... ) == "plain-token-value-at-least-32-chars-long"
        True
    """
    ps = process or ProcessSettings()
    env_token = (ps.gateway_token or "").strip()
    ref_raw: str | None = None
    if workspace.gateway is not None and workspace.gateway.token:
        ref_raw = str(workspace.gateway.token).strip()
    return await resolve_config_ref(
        workspace,
        content_root=content_root,
        ref_raw=ref_raw,
        process=ps,
        process_env_override=env_token or None,
        unresolved_log_label="gateway_token_ref_unresolved",
    )


__all__ = [
    "GATEWAY_TOKEN_CONFIG_REF",
    "GATEWAY_TOKEN_HEX_LEN",
    "GATEWAY_TOKEN_LOGICAL_KEY",
    "GATEWAY_TOKEN_MIN_CHARS",
    "generate_gateway_token",
    "resolve_config_ref",
    "resolve_gateway_token_ref",
    "validate_gateway_token_plaintext",
]
