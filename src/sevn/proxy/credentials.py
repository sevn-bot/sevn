"""Build ``ProxySettings`` from workspace secrets and provider metadata.

Module: sevn.proxy.credentials
Depends: asyncio, os, pathlib, sevn.config.model_resolution, sevn.config.workspace_config,
    sevn.proxy.settings, sevn.security.secrets.factory

Exports:
    ProviderCredentialEntry — resolved key + base URLs for one provider.
    ProviderCredentials — boot-time map of provider name → resolved key + base URLs.
    credential_unresolved_detail — 503 detail string naming an unresolved provider.
    resolve_request_credential — per-request key + base_url from model id (D3).
    resolve_oauth_request_credential — OAuth bearer + account id for Codex transport (D1).
    resolve_oauth_request_credential_async — async variant for ASGI handlers.
    build_proxy_settings — merge env, secrets chain, and MiniMax ``base_url``.
    build_proxy_settings_sync — sync wrapper for uvicorn factory boot.

Examples:
    >>> from sevn.proxy.credentials import build_proxy_settings_sync
    >>> import inspect
    >>> inspect.iscoroutinefunction(build_proxy_settings_sync) is False
    True
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sevn.config.model_resolution import (
    is_minimax_model,
    resolve_minimax_anthropic_base_url,
    resolve_minimax_openai_base_url,
    workspace_has_minimax_catalog_model,
)
from sevn.config.provider_registry import resolve_provider_binding, resolve_provider_for_model_id
from sevn.config.sections.providers import (
    provider_entry_dict,
    providers_section_dict,
    resolve_auth_mode,
)
from sevn.config.workspace_config import (
    SecretsBackendSectionConfig,
    WorkspaceConfig,
    effective_encrypted_file_key_source,
)
from sevn.proxy.codex_transport import codex_responses_url
from sevn.proxy.settings import ProxySettings
from sevn.security.oauth.constants import CODEX_RESPONSES_BASE_URL
from sevn.security.oauth.credential import CodexOAuthCredential, resolution_probe_credential
from sevn.security.secrets.cache import ResolvedSecretsCache
from sevn.security.secrets.chain import SecretsChain, get_secret_resilient
from sevn.security.secrets.errors import SecretUnresolvedError
from sevn.security.secrets.factory import secrets_chain_from_workspace
from sevn.security.secrets.passphrase_prime import reconcile_unlock_env_with_keychain
from sevn.security.secrets.value_expand import (
    EnvUnresolvedError,
    expand_refs_env_then_secret,
)

_ANTHROPIC_ROUTE = "/llm/anthropic/messages"
_OPENAI_CHAT_ROUTE = "/llm/openai/chat/completions"
_SECRET_REF = re.compile(r"^\$\{SECRET:([^}]+)\}$")

BRAVE_SECRET_ID = "web.brave.api_key"  # nosec B105 — logical secret id, not a secret value
"""Logical secret id for the Brave Search key: ``sevn secrets put web.brave.api_key``.

Resolved from the workspace secrets chain in :func:`build_proxy_settings` so
``web_search`` works without a shell ``BRAVE_API_KEY`` env var. An explicit
``BRAVE_API_KEY`` in the proxy environment still takes precedence.
"""
_PROVIDERS_META_KEYS = frozenset(
    {"tier_default", "models", "native_model", "fallback_chain", "use_main_model_for_all"}
)


@dataclass
class ProviderCredentialEntry:
    """Resolved credential + base URLs for one provider name."""

    api_key: str | None = None
    base_url: str | None = None
    openai_base_url: str | None = None
    anthropic_base_url: str | None = None


@dataclass
class ProviderCredentials:
    """Boot-time provider registry map attached to ``app.state`` (W3)."""

    by_name: dict[str, ProviderCredentialEntry] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _ProviderKeyCacheEntry:
    """One cached provider key with monotonic expiry."""

    value: str
    expires_at: float


def credential_unresolved_detail(provider_name: str) -> str:
    """Return a 503 detail string naming the unresolved provider (D7).

    Args:
        provider_name (str): Provider registry key.

    Returns:
        str: Operator-facing detail without secret material.

    Examples:
        >>> credential_unresolved_detail("minimax")
        'minimax credential not configured'
    """
    return f"{provider_name} credential not configured"


def _resolve_cache_ttl(app_state: Any) -> int:
    """Read secrets-cache TTL from ``app.state.secrets_cache`` when present.

    Args:
        app_state (Any): Starlette ``app.state``.

    Returns:
        int: TTL seconds; ``0`` when cache is absent.

    Examples:
        >>> _resolve_cache_ttl(object())
        0
    """
    cache = getattr(app_state, "secrets_cache", None)
    if isinstance(cache, ResolvedSecretsCache):
        return cache.ttl_seconds
    return 0


def _binding_key_from_map(app_state: Any, provider_name: str) -> str | None:
    """Return a provider binding key from the boot map with per-provider TTL cache.

    Args:
        app_state (Any): Starlette ``app.state``.
        provider_name (str): Provider registry key.

    Returns:
        str | None: Resolved binding key when present.

    Examples:
        >>> _binding_key_from_map(object(), "openai") is None
        True
    """
    ttl = _resolve_cache_ttl(app_state)
    now = time.monotonic()
    cache = getattr(app_state, "_provider_resolve_cache", None)
    if isinstance(cache, dict):
        hit = cache.get(provider_name)
        if isinstance(hit, _ProviderKeyCacheEntry) and (ttl == 0 or hit.expires_at > now):
            return hit.value

    provider_creds = getattr(app_state, "provider_credentials", None)
    if not isinstance(provider_creds, ProviderCredentials):
        return None
    entry = provider_creds.by_name.get(provider_name)
    if entry is None or not entry.api_key:
        return None

    if ttl > 0:
        if not isinstance(cache, dict):
            cache = {}
            app_state._provider_resolve_cache = cache
        cache[provider_name] = _ProviderKeyCacheEntry(
            value=entry.api_key, expires_at=now + float(ttl)
        )
    return entry.api_key


def _legacy_route_key(settings: ProxySettings, route: str, model_id: str) -> str | None:
    """Return today's route-bucket key with MiniMax cross-fallback (D4).

    Args:
        settings (ProxySettings): Boot-time proxy settings.
        route (str): Proxy path.
        model_id (str): Catalog model id from the request body.

    Returns:
        str | None: Legacy bucket key when configured.

    Examples:
        >>> s = ProxySettings(anthropic_api_key="sk-a", openai_api_key="sk-o")
        >>> _legacy_route_key(s, _ANTHROPIC_ROUTE, "anthropic/claude")
        'sk-a'
    """
    is_minimax = is_minimax_model(model_id)
    if route == _ANTHROPIC_ROUTE:
        api_key = settings.anthropic_api_key
        if is_minimax and not api_key:
            api_key = settings.openai_api_key
        return api_key
    if route == _OPENAI_CHAT_ROUTE:
        api_key = settings.openai_api_key
        if is_minimax and not api_key:
            api_key = settings.anthropic_api_key
        return api_key
    return settings.openai_api_key


def _route_bucket_key(settings: ProxySettings, route: str) -> str | None:
    """Return the per-route bucket without MiniMax cross-fallback (D3 step 2).

    Args:
        settings (ProxySettings): Boot-time proxy settings.
        route (str): Proxy path.

    Returns:
        str | None: Route bucket key when set.

    Examples:
        >>> s = ProxySettings(anthropic_api_key="sk-a")
        >>> _route_bucket_key(s, _ANTHROPIC_ROUTE)
        'sk-a'
    """
    if route == _ANTHROPIC_ROUTE:
        return settings.anthropic_api_key
    if route == _OPENAI_CHAT_ROUTE:
        return settings.openai_api_key
    return settings.openai_api_key


def _wizard_provider_key(_settings: ProxySettings) -> str | None:
    """Deprecated wizard shortcut — per-provider bindings resolve at boot (D3).

    Args:
        _settings (ProxySettings): Unused; kept for call-site compatibility during removal.

    Returns:
        str | None: Always ``None``.

    Examples:
        >>> _wizard_provider_key(ProxySettings(openai_api_key="sk-w")) is None
        True
    """
    return None


def _resolve_api_key(
    cfg: WorkspaceConfig,
    app_state: Any,
    *,
    provider_name: str,
    model_id: str,
    route: str,
) -> str | None:
    """Resolve upstream API key using D3 precedence or D4 legacy buckets.

    Args:
        cfg (WorkspaceConfig): Parsed ``sevn.json``.
        app_state (Any): Starlette ``app.state``.
        provider_name (str): Provider registry key for the model.
        model_id (str): Catalog model id from the request body.
        route (str): Proxy path.

    Returns:
        str | None: Resolved key when available.

    Examples:
        >>> cfg = WorkspaceConfig.minimal()
        >>> st = type("S", (), {"settings": ProxySettings(anthropic_api_key="sk-a")})()
        >>> _resolve_api_key(cfg, st, provider_name="anthropic", model_id="anthropic/claude", route=_ANTHROPIC_ROUTE)
        'sk-a'
    """
    settings: ProxySettings = app_state.settings
    # A dedicated per-provider key from the boot credentials map wins for ANY provider — including
    # MiniMax, whose entry is populated from the wizard/provider key at boot. This bypasses the
    # legacy openai/anthropic route-bucket cross-fallback the operator does not want.
    mapped = _binding_key_from_map(app_state, provider_name)
    if mapped:
        return mapped
    binding = resolve_provider_binding(cfg, provider_name)
    if binding.api_key_ref is not None:
        key = _route_bucket_key(settings, route)
        if key:
            return key
        return _wizard_provider_key(settings)
    return _legacy_route_key(settings, route, model_id)


def _resolve_base_url(
    cfg: WorkspaceConfig,
    app_state: Any,
    *,
    provider_name: str,
    model_id: str,
    route: str,
) -> str:
    """Resolve upstream base URL for one provider and route (D5).

    Args:
        cfg (WorkspaceConfig): Parsed ``sevn.json``.
        app_state (Any): Starlette ``app.state``.
        provider_name (str): Provider registry key.
        model_id (str): Catalog model id from the request body.
        route (str): Proxy path.

    Returns:
        str: Base URL for upstream forwarding.

    Examples:
        >>> cfg = WorkspaceConfig.minimal()
        >>> st = type("S", (), {"settings": ProxySettings()})()
        >>> _resolve_base_url(cfg, st, provider_name="anthropic", model_id="anthropic/claude", route=_ANTHROPIC_ROUTE)
        'https://api.anthropic.com'
    """
    settings: ProxySettings = app_state.settings
    is_minimax = is_minimax_model(model_id)
    provider_creds = getattr(app_state, "provider_credentials", None)
    entry: ProviderCredentialEntry | None = None
    if isinstance(provider_creds, ProviderCredentials):
        entry = provider_creds.by_name.get(provider_name)

    if route == _ANTHROPIC_ROUTE:
        if entry is not None and entry.anthropic_base_url:
            return entry.anthropic_base_url
        if is_minimax:
            configured = _minimax_section_base_url(cfg)
            return resolve_minimax_anthropic_base_url(configured)
        return settings.anthropic_base_url

    if route == _OPENAI_CHAT_ROUTE:
        if entry is not None and entry.openai_base_url:
            return entry.openai_base_url
        if is_minimax:
            configured = _minimax_section_openai_base_url(cfg)
            return resolve_minimax_openai_base_url(configured)
        return settings.openai_base_url

    return settings.openai_base_url


def resolve_request_credential(
    cfg: WorkspaceConfig,
    app_state: Any,
    model_id: str,
    route: str,
) -> tuple[str | None, str]:
    """Resolve upstream API key and base URL for one proxy request (D3).

    Precedence when ``providers.<name>.api_key`` is set (first non-empty): provider
    binding → route bucket env vars. Without a binding, D4 legacy bucket behavior
    (including MiniMax cross-fallback) is preserved.

    Args:
        cfg (WorkspaceConfig): Parsed ``sevn.json``.
        app_state (Any): Starlette ``app.state`` (settings, secrets_cache, provider map).
        model_id (str): Catalog model id from the request body.
        route (str): Proxy path (e.g. ``/llm/anthropic/messages``).

    Returns:
        tuple[str | None, str]: ``(api_key, base_url)`` for upstream forwarding.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal()
        >>> st = type(
        ...     "S",
        ...     (),
        ...     {
        ...         "settings": ProxySettings(anthropic_api_key="sk-a"),
        ...         "provider_credentials": ProviderCredentials(),
        ...     },
        ... )()
        >>> key, base = resolve_request_credential(cfg, st, "anthropic/claude", _ANTHROPIC_ROUTE)
        >>> key
        'sk-a'
    """
    provider_name = resolve_provider_for_model_id(cfg, model_id)
    api_key = _resolve_api_key(
        cfg,
        app_state,
        provider_name=provider_name,
        model_id=model_id,
        route=route,
    )
    base_url = _resolve_base_url(
        cfg,
        app_state,
        provider_name=provider_name,
        model_id=model_id,
        route=route,
    )
    return api_key, base_url


def _oauth_codex_base_url() -> str:
    """Return the Codex Responses transport base URL (D7).

    Returns:
        str: ``https://chatgpt.com/backend-api`` (full path via :func:`codex_responses_url`).

    Examples:
        >>> _oauth_codex_base_url()
        'https://chatgpt.com/backend-api'
    """
    return CODEX_RESPONSES_BASE_URL


def _resolve_oauth_credential_sync(app_state: Any) -> CodexOAuthCredential:
    """Load Codex OAuth credential from ``app.state`` or the secrets chain.

    Args:
        app_state (Any): Starlette ``app.state``.

    Returns:
        CodexOAuthCredential: Fresh or cached credential.

    Raises:
        OauthCredentialMissingError: When ``oauth.openai`` is not configured.

    Examples:
        >>> import pytest  # doctest: +SKIP
        >>> cred = _resolve_oauth_credential_sync(type("S", (), {})())  # doctest: +SKIP
        >>> cred.account_id  # doctest: +SKIP
        'acct-resolution-probe'
    """
    from sevn.proxy.oauth_lifecycle import (
        OauthCredentialMissingError,
        ensure_fresh_oauth_credential,
    )

    cached = getattr(app_state, "codex_oauth_credential", None)
    cache = getattr(app_state, "secrets_cache", None)
    if isinstance(cache, ResolvedSecretsCache):
        coro = ensure_fresh_oauth_credential(cache.chain)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            credential = asyncio.run(coro)
        else:
            with ThreadPoolExecutor(max_workers=1) as pool:
                credential = pool.submit(asyncio.run, coro).result()
        app_state.codex_oauth_credential = credential
        return credential
    if isinstance(cached, CodexOAuthCredential):
        return cached
    try:
        return resolution_probe_credential()
    except RuntimeError:
        msg = (
            "oauth.openai credential is missing; run `sevn providers oauth login --provider openai`"
        )
        raise OauthCredentialMissingError(msg) from None


def resolve_oauth_request_credential(
    cfg: WorkspaceConfig,
    app_state: Any,
    model_id: str,
    route: str,
) -> tuple[str, str, str]:
    """Resolve OAuth bearer, account id, and Codex Responses base URL (D1/D3).

    Does not fall back to ``api_key``, route buckets, or ``SEVN_PROVIDER_API_KEY`` (D4).

    Args:
        cfg (WorkspaceConfig): Parsed ``sevn.json``.
        app_state (Any): Starlette ``app.state``.
        model_id (str): Catalog model id from the request body.
        route (str): Proxy path (unused; kept for symmetry with :func:`resolve_request_credential`).

    Returns:
        tuple[str, str, str]: ``(access_token, account_id, base_url)``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(providers={"openai": {"auth_mode": "oauth"}})
        >>> st = type("S", (), {"provider_credentials": ProviderCredentials()})()
        >>> bearer, acct, base = resolve_oauth_request_credential(
        ...     cfg, st, "openai/gpt-4o", _OPENAI_CHAT_ROUTE
        ... )
        >>> "chatgpt.com" in base
        True
    """
    _ = model_id, route
    if resolve_auth_mode(cfg.providers, "openai") != "oauth":
        msg = "resolve_oauth_request_credential requires providers.openai.auth_mode=oauth"
        raise ValueError(msg)
    credential = _resolve_oauth_credential_sync(app_state)
    return credential.access, credential.account_id, _oauth_codex_base_url()


async def resolve_oauth_request_credential_async(
    cfg: WorkspaceConfig,
    app_state: Any,
    model_id: str,
    route: str,
) -> tuple[str, str, str]:
    """Async variant of :func:`resolve_oauth_request_credential` for ASGI handlers.

    Args:
        cfg (WorkspaceConfig): Parsed ``sevn.json``.
        app_state (Any): Starlette ``app.state``.
        model_id (str): Catalog model id from the request body.
        route (str): Proxy path.

    Returns:
        tuple[str, str, str]: ``(access_token, account_id, codex_responses_url)``.

    Examples:
        >>> # Covered by tests/proxy/test_codex_oauth_transport.py.
        >>> True
        True
    """
    _ = model_id, route
    if resolve_auth_mode(cfg.providers, "openai") != "oauth":
        msg = "resolve_oauth_request_credential requires providers.openai.auth_mode=oauth"
        raise ValueError(msg)
    from sevn.proxy.oauth_lifecycle import (
        OauthCredentialMissingError,
        ensure_fresh_oauth_credential,
    )

    cached = getattr(app_state, "codex_oauth_credential", None)
    cache = getattr(app_state, "secrets_cache", None)
    if isinstance(cache, ResolvedSecretsCache):
        credential = await ensure_fresh_oauth_credential(cache.chain)
        app_state.codex_oauth_credential = credential
    elif isinstance(cached, CodexOAuthCredential):
        credential = cached
    else:
        try:
            credential = resolution_probe_credential()
        except RuntimeError as exc:
            msg = "oauth.openai credential is missing; run `sevn providers oauth login --provider openai`"
            raise OauthCredentialMissingError(msg) from exc
    return credential.access, credential.account_id, codex_responses_url()


async def _resolve_credential_ref(
    ref: str,
    chain: SecretsChain,
    cache: ResolvedSecretsCache,
) -> str | None:
    """Expand one ``providers.<name>.api_key`` ref via the secrets chain.

    Args:
        ref (str): Literal or ``${SECRET:…}`` / ``${ENV:…}`` reference.
        chain (SecretsChain): Workspace secrets chain.
        cache (ResolvedSecretsCache): TTL cache for secret expansion.

    Returns:
        str | None: Resolved plaintext when available.

    Examples:
        >>> import asyncio
        >>> from sevn.security.secrets.chain import SecretsChain
        >>> async def _run():
        ...     class _M:
        ...         async def get(self, k: str) -> str | None:
        ...             return {"k": "V"}.get(k)
        ...         async def set(self, k: str, v: str) -> None: ...
        ...         async def delete(self, k: str) -> None: ...
        ...     c = ResolvedSecretsCache(SecretsChain([_M()]), ttl_seconds=0)
        ...     return await _resolve_credential_ref("sk-lit", SecretsChain([_M()]), c)
        >>> asyncio.run(_run())
        'sk-lit'
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


async def _build_provider_credentials_map(
    workspace_config: WorkspaceConfig,
    chain: SecretsChain,
    *,
    ttl_seconds: int,
) -> ProviderCredentials:
    """Resolve ``providers.<name>`` keys and base URLs at proxy boot.

    Args:
        workspace_config (WorkspaceConfig): Parsed ``sevn.json``.
        chain (SecretsChain): Workspace secrets chain.
        ttl_seconds (int): TTL for secret expansion cache.

    Returns:
        ProviderCredentials: Provider name → resolved entry map.

    Examples:
        >>> import asyncio
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.security.secrets.cache import ResolvedSecretsCache
        >>> from sevn.security.secrets.chain import SecretsChain
        >>> class _M:
        ...     async def get(self, k: str) -> str | None:
        ...         return None
        ...     async def set(self, k: str, v: str) -> None: ...
        ...     async def delete(self, k: str) -> None: ...
        >>> async def _run():
        ...     chain = SecretsChain([_M()])
        ...     return await _build_provider_credentials_map(
        ...         WorkspaceConfig.minimal(providers={}),
        ...         chain,
        ...         ttl_seconds=0,
        ...     )
        >>> isinstance(asyncio.run(_run()), ProviderCredentials)
        True
    """
    providers = providers_section_dict(workspace_config.providers)
    cache = ResolvedSecretsCache(chain, ttl_seconds=ttl_seconds)
    by_name: dict[str, ProviderCredentialEntry] = {}
    for name, raw in providers.items():
        if name in _PROVIDERS_META_KEYS:
            continue
        if not isinstance(raw, dict):
            continue
        binding = resolve_provider_binding(workspace_config, name)
        if not any(
            (
                binding.api_key_ref,
                binding.base_url,
                binding.openai_base_url,
                binding.anthropic_base_url,
            )
        ):
            continue
        api_key: str | None = None
        if binding.api_key_ref:
            api_key = await _resolve_credential_ref(binding.api_key_ref, chain, cache)
        anthropic_url = binding.anthropic_base_url
        openai_url = binding.openai_base_url
        base = binding.base_url
        if name == "minimax":
            anthropic_url = anthropic_url or resolve_minimax_anthropic_base_url(base)
            openai_url = openai_url or resolve_minimax_openai_base_url(binding.openai_base_url)
        elif base and not anthropic_url:
            anthropic_url = base
        by_name[name] = ProviderCredentialEntry(
            api_key=api_key,
            base_url=base,
            openai_base_url=openai_url,
            anthropic_base_url=anthropic_url,
        )
    return ProviderCredentials(by_name=by_name)


def _minimax_section_base_url(workspace_config: WorkspaceConfig) -> str | None:
    """Read ``providers.minimax.base_url`` from the workspace ``providers`` block.

    Args:
        workspace_config (WorkspaceConfig): Parsed workspace config.

    Returns:
        str | None: Configured base URL or ``None`` when absent.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     providers={"minimax": {"base_url": "https://api.minimax.io/anthropic/v1"}},
        ... )
        >>> _minimax_section_base_url(cfg)
        'https://api.minimax.io/anthropic/v1'
    """
    entry = provider_entry_dict(workspace_config.providers, "minimax")
    base_url = entry.get("base_url")
    if isinstance(base_url, str) and base_url.strip():
        return base_url.strip()
    return None


def _minimax_section_openai_base_url(workspace_config: WorkspaceConfig) -> str | None:
    """Read ``providers.minimax.openai_base_url`` from workspace ``providers`` block.

    Args:
        workspace_config (WorkspaceConfig): Parsed workspace config.

    Returns:
        str | None: Configured OpenAI-compatible base URL or ``None`` when absent.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     providers={"minimax": {"openai_base_url": "https://custom.minimax.io/v1"}},
        ... )
        >>> _minimax_section_openai_base_url(cfg)
        'https://custom.minimax.io/v1'
    """
    entry = provider_entry_dict(workspace_config.providers, "minimax")
    base_url = entry.get("openai_base_url")
    if isinstance(base_url, str) and base_url.strip():
        return base_url.strip()
    return None


async def build_proxy_settings(
    *,
    workspace_config: WorkspaceConfig,
    content_root: Path,
    env_settings: ProxySettings | None = None,
) -> ProxySettings:
    """Merge process env, secrets chain, and provider registry metadata.

    ``openai_api_key`` / ``anthropic_api_key`` come from ``OPENAI_API_KEY`` /
    ``ANTHROPIC_API_KEY`` env overrides only. Per-provider credentials resolve
    from ``providers.<name>.api_key`` refs via :func:`_build_provider_credentials_map`.

    When any workspace model id uses the ``minimax/`` catalog prefix,
    ``anthropic_base_url`` is set to the MiniMax Anthropic-compatible endpoint.

    Args:
        workspace_config (WorkspaceConfig): Parsed ``sevn.json``.
        content_root (Path): Workspace content anchor for secrets backends.
        env_settings (ProxySettings | None): Pre-loaded env settings; default
            constructs ``ProxySettings()`` from the process environment.

    Returns:
        ProxySettings: Settings wired into ``/llm/*`` handlers.

    Examples:
        >>> import asyncio
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.proxy.settings import ProxySettings
        >>> td = Path(tempfile.mkdtemp())
        >>> cfg = WorkspaceConfig.minimal(providers={})
        >>> out = asyncio.run(
        ...     build_proxy_settings(
        ...         workspace_config=cfg,
        ...         content_root=td,
        ...         env_settings=ProxySettings(openai_api_key="sk-env"),
        ...     )
        ... )
        >>> out.openai_api_key
        'sk-env'
    """
    settings = env_settings if env_settings is not None else ProxySettings()
    chain = secrets_chain_from_workspace(content_root, workspace_config.secrets_backend)
    # Self-unlock at daemon boot: the launchd session loses the unlock var on logout, so reconcile
    # it against the macOS login Keychain (read directly, not via the chain — an encrypted_file-only
    # store cannot be unlocked with a key kept inside itself). Reconcile (not prime) is required so a
    # *stale/wrong* ``launchctl setenv`` value is replaced with the Keychain copy: a mismatched
    # unlock var otherwise trips ``AEAD decrypt failed`` on every boot and launchd ``KeepAlive``
    # crash-loops the proxy forever (a fill-only prime is a no-op when the var is already set).
    # Falls back to the chain for hosts where the unlock var lives in a chain backend, not keychain.
    key_source = effective_encrypted_file_key_source(workspace_config.secrets_backend)
    if await reconcile_unlock_env_with_keychain(key_source=key_source):
        chain = secrets_chain_from_workspace(content_root, workspace_config.secrets_backend)
    elif not os.environ.get("SEVN_SECRETS_PASSPHRASE", "").strip():
        passphrase = await chain.get_resilient("SEVN_SECRETS_PASSPHRASE")
        if passphrase:
            os.environ["SEVN_SECRETS_PASSPHRASE"] = passphrase
            chain = secrets_chain_from_workspace(content_root, workspace_config.secrets_backend)

    uses_minimax = workspace_has_minimax_catalog_model(workspace_config)
    if uses_minimax:
        minimax_url = resolve_minimax_anthropic_base_url(
            _minimax_section_base_url(workspace_config)
        )
        if settings.anthropic_base_url == "https://api.anthropic.com":
            settings = settings.model_copy(update={"anthropic_base_url": minimax_url})

    ttl = (workspace_config.secrets_backend or SecretsBackendSectionConfig()).cache_ttl_seconds
    provider_credentials = await _build_provider_credentials_map(
        workspace_config,
        chain,
        ttl_seconds=ttl,
    )
    updates: dict[str, Any] = {"provider_credentials": provider_credentials}
    # Resolve the Brave Search key from the secrets chain when not already provided
    # via the ``BRAVE_API_KEY`` env override, so ``sevn secrets put web.brave.api_key``
    # enables ``web_search`` without a shell env var.
    if not settings.brave_api_key:
        brave_key = await _resolve_brave_key(chain)
        if brave_key:
            updates["brave_api_key"] = brave_key
    return settings.model_copy(update=updates)


async def _resolve_brave_key(chain: SecretsChain) -> str | None:
    """Resolve the Brave Search API key from the secrets chain (``None`` if unset).

    Args:
        chain (SecretsChain): Workspace secrets chain.

    Returns:
        str | None: Trimmed key stored under :data:`BRAVE_SECRET_ID`, or ``None``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_resolve_brave_key)
        True
    """
    try:
        value = await chain.get_resilient(BRAVE_SECRET_ID)
    except SecretUnresolvedError:
        return None
    trimmed = (value or "").strip()
    return trimmed or None


def build_proxy_settings_sync(
    *,
    workspace_config: WorkspaceConfig,
    content_root: Path,
    env_settings: ProxySettings | None = None,
) -> ProxySettings:
    """Synchronous wrapper around :func:`build_proxy_settings` for factory boot.

    Args:
        workspace_config (WorkspaceConfig): Parsed workspace config.
        content_root (Path): Workspace content root.
        env_settings (ProxySettings | None): Optional pre-loaded env settings.

    Returns:
        ProxySettings: Merged proxy credentials and upstream URLs.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> td = Path(tempfile.mkdtemp())
        >>> cfg = WorkspaceConfig.minimal(providers={})
        >>> build_proxy_settings_sync(workspace_config=cfg, content_root=td).openai_base_url
        'https://api.openai.com/v1'
    """
    coro = build_proxy_settings(
        workspace_config=workspace_config,
        content_root=content_root,
        env_settings=env_settings,
    )
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


__all__ = [
    "ProviderCredentialEntry",
    "ProviderCredentials",
    "build_proxy_settings",
    "build_proxy_settings_sync",
    "credential_unresolved_detail",
    "resolve_oauth_request_credential",
    "resolve_oauth_request_credential_async",
    "resolve_request_credential",
]
