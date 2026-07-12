"""Resolve ``skills.openwiki`` credential refs into subprocess env vars.

Module: sevn.skills.openwiki_secrets
Depends: re, sevn.config.workspace_config, sevn.security.secrets

Exports:
    openwiki_credentials_hint — operator-facing missing-credentials message.
    openwiki_credentials_resolved — probe whether LLM credentials resolve.
    merge_openwiki_proc_env — inject OpenWiki provider/model/API keys into env.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from sevn.config.provider_registry import provider_credential_ref
from sevn.config.provider_secrets import assigned_provider_names_from_doc
from sevn.config.workspace_config import WorkspaceConfig
from sevn.security.secrets.cache import ResolvedSecretsCache
from sevn.security.secrets.chain import SecretsChain, get_secret_resilient
from sevn.security.secrets.errors import SecretUnresolvedError
from sevn.security.secrets.factory import secrets_chain_from_workspace
from sevn.security.secrets.value_expand import EnvUnresolvedError, expand_refs_env_then_secret

OPENWIKI_LLM_API_KEY_SECRET: Final[str] = "integration.openwiki.llm_api_key"

_OPENWIKI_PROVIDER_ENV = "OPENWIKI_PROVIDER"
_OPENWIKI_MODEL_ID_ENV = "OPENWIKI_MODEL_ID"

_PROVIDER_API_KEY_ENV: dict[str, str] = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "baseten": "BASETEN_API_KEY",
}

_API_KEYS_ENV: dict[str, str] = {
    "openrouter_api_key": "OPENROUTER_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "fireworks_api_key": "FIREWORKS_API_KEY",
    "baseten_api_key": "BASETEN_API_KEY",
    "langsmith_api_key": "LANGSMITH_API_KEY",
}

_SECRET_REF = re.compile(r"^\$\{SECRET:([^}]+)\}$")
_DEFAULT_PROVIDER = "openrouter"
_SECRETS_CACHE_TTL_SECONDS = 300


def openwiki_credentials_hint() -> str:
    """Return operator guidance when OpenWiki LLM credentials are missing.

    Returns:
        str: Plain-text hint referencing sevn secrets and ``sevn.json`` refs.

    Examples:
        >>> "sevn secrets set" in openwiki_credentials_hint()
        True
    """
    return (
        "configure OpenWiki credentials via sevn secrets "
        f"(e.g. `sevn secrets set {OPENWIKI_LLM_API_KEY_SECRET}`), set "
        "`skills.openwiki.api_key`, or rely on auto-map from assigned provider "
        "`providers.<name>.api_key` secrets"
    )


def _openwiki_block(cfg: WorkspaceConfig | None) -> dict[str, object] | None:
    """Return the ``skills.openwiki`` config block when present.

    Args:
        cfg (WorkspaceConfig | None): Loaded workspace config.

    Returns:
        dict[str, object] | None: OpenWiki skill settings or ``None``.

    Examples:
        >>> _openwiki_block(None) is None
        True
    """
    if cfg is None or cfg.skills is None:
        return None
    block = cfg.skills.get("openwiki")
    return block if isinstance(block, dict) else None


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


def _provider_name(block: dict[str, object]) -> str:
    """Return normalized OpenWiki provider id from config.

    Args:
        block (dict[str, object]): ``skills.openwiki`` config block.

    Returns:
        str: Provider id supported by OpenWiki (defaults to ``openrouter``).

    Examples:
        >>> _provider_name({"provider": "openai"})
        'openai'
    """
    raw = block.get("provider")
    if isinstance(raw, str) and raw.strip():
        provider = raw.strip().lower()
        if provider in _PROVIDER_API_KEY_ENV:
            return provider
    return _DEFAULT_PROVIDER


async def _resolve_auto_provider_api_key(
    cfg: WorkspaceConfig,
    *,
    chain: SecretsChain,
    cache: ResolvedSecretsCache,
    preferred_provider: str,
) -> tuple[str, str] | None:
    """Resolve an API key from assigned provider secrets or the OpenWiki integration secret.

    Args:
        cfg (WorkspaceConfig): Parsed workspace config.
        chain (SecretsChain): Workspace secrets chain.
        cache (ResolvedSecretsCache): Secret expansion cache.
        preferred_provider (str): OpenWiki provider id from skill config.

    Returns:
        tuple[str, str] | None: ``(provider_id, plaintext_key)`` when resolved.

    Examples:
        >>> _resolve_auto_provider_api_key.__name__
        '_resolve_auto_provider_api_key'
    """
    assigned = assigned_provider_names_from_doc(cfg.model_dump())
    assigned_lower = {name.lower(): name for name in assigned}

    if preferred_provider in assigned_lower:
        registry_name = assigned_lower[preferred_provider]
        ref = provider_credential_ref(cfg, registry_name)
        if ref:
            resolved = await _resolve_credential_ref(ref, chain, cache)
            if resolved:
                return preferred_provider, resolved

    for registry_name in sorted(assigned):
        provider_id = registry_name.lower()
        if provider_id not in _PROVIDER_API_KEY_ENV:
            continue
        ref = provider_credential_ref(cfg, registry_name)
        if not ref:
            continue
        resolved = await _resolve_credential_ref(ref, chain, cache)
        if resolved:
            return provider_id, resolved

    integration_key = await get_secret_resilient(chain, OPENWIKI_LLM_API_KEY_SECRET)
    if integration_key and integration_key.strip():
        return preferred_provider, integration_key.strip()

    return None


async def _apply_openwiki_api_key_env(
    env: dict[str, str],
    block: dict[str, object],
    cfg: WorkspaceConfig,
    *,
    chain: SecretsChain,
    cache: ResolvedSecretsCache,
) -> str:
    """Resolve and inject OpenWiki provider/API-key env vars into ``env``.

    Args:
        env (dict[str, str]): Mutable subprocess environment.
        block (dict[str, object]): ``skills.openwiki`` config block.
        cfg (WorkspaceConfig): Parsed workspace config.
        chain (SecretsChain): Workspace secrets chain.
        cache (ResolvedSecretsCache): Secret expansion cache.

    Returns:
        str: Effective provider id after auto-map (may differ from config default).

    Examples:
        >>> _apply_openwiki_api_key_env.__name__
        '_apply_openwiki_api_key_env'
    """
    provider = _provider_name(block)
    env.setdefault(_OPENWIKI_PROVIDER_ENV, provider)

    api_key_ref = block.get("api_key")
    if isinstance(api_key_ref, str) and api_key_ref.strip():
        resolved = await _resolve_credential_ref(api_key_ref, chain, cache)
        if resolved:
            env.setdefault(_PROVIDER_API_KEY_ENV[provider], resolved)

    api_keys = block.get("api_keys")
    if isinstance(api_keys, dict):
        for config_key, env_var in _API_KEYS_ENV.items():
            raw = api_keys.get(config_key)
            if not isinstance(raw, str) or not raw.strip():
                continue
            resolved = await _resolve_credential_ref(raw, chain, cache)
            if resolved:
                env.setdefault(env_var, resolved)

    provider_env = _PROVIDER_API_KEY_ENV[provider]
    if not env.get(provider_env):
        auto = await _resolve_auto_provider_api_key(
            cfg,
            chain=chain,
            cache=cache,
            preferred_provider=provider,
        )
        if auto is not None:
            auto_provider, auto_key = auto
            env.setdefault(_PROVIDER_API_KEY_ENV[auto_provider], auto_key)
            env[_OPENWIKI_PROVIDER_ENV] = auto_provider
            provider = auto_provider

    return provider


async def openwiki_credentials_resolved(
    cfg: WorkspaceConfig | None,
    *,
    content_root: Path,
) -> tuple[bool, str]:
    """Return whether OpenWiki LLM credentials can be resolved for this workspace.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config.
        content_root (Path): Workspace content root.

    Returns:
        tuple[bool, str]: ``(ok, detail)`` for doctor probes and diagnostics.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> asyncio.run(openwiki_credentials_resolved(None, content_root=Path(".")))[0]
        False
    """
    block = _openwiki_block(cfg)
    if block is None or cfg is None:
        return False, "skills.openwiki block missing"

    chain = secrets_chain_from_workspace(content_root, cfg.secrets_backend)
    cache = ResolvedSecretsCache(chain, ttl_seconds=_SECRETS_CACHE_TTL_SECONDS)
    env: dict[str, str] = {}
    provider = await _apply_openwiki_api_key_env(
        env,
        block,
        cfg,
        chain=chain,
        cache=cache,
    )
    provider_env = _PROVIDER_API_KEY_ENV[provider]
    if env.get(provider_env):
        return True, f"LLM provider API key resolved for {provider!r} ({provider_env})"

    return False, openwiki_credentials_hint()


async def merge_openwiki_proc_env(
    env: dict[str, str],
    *,
    content_root: Path,
    cfg: WorkspaceConfig | None,
) -> None:
    """Inject OpenWiki provider/model/API key env vars from sevn secrets.

    Resolved values are applied with ``setdefault`` so explicit operator env wins.
    OpenWiki subprocesses prefer ``process.env`` over ``~/.openwiki/.env`` when set.

    Args:
        env (dict[str, str]): Mutable subprocess environment (updated in place).
        content_root (Path): Workspace content root for secrets chain resolution.
        cfg (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        None

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(merge_openwiki_proc_env)
        True
    """
    block = _openwiki_block(cfg)
    if block is None or cfg is None:
        return

    model_id = block.get("model_id")
    if isinstance(model_id, str) and model_id.strip():
        env.setdefault(_OPENWIKI_MODEL_ID_ENV, model_id.strip())

    chain = secrets_chain_from_workspace(content_root, cfg.secrets_backend if cfg else None)
    cache = ResolvedSecretsCache(chain, ttl_seconds=_SECRETS_CACHE_TTL_SECONDS)
    await _apply_openwiki_api_key_env(
        env,
        block,
        cfg,
        chain=chain,
        cache=cache,
    )
