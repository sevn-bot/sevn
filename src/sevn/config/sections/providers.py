"""Providers subtree models for ``sevn.json``.

Module: sevn.config.sections.providers
Depends: pydantic

Exports:
    ProviderEntryConfig — ``providers.<name>`` entry (D2 sub-keys).
    ProviderModelOverrideConfig — ``providers.models.<id>`` override block.
    ProvidersWorkspaceSectionConfig — typed ``providers`` subtree.
    providers_section_dict — merged dict for legacy ``providers`` accessors.
    provider_entry_dict — one named provider entry as a plain mapping.
    resolve_consumption_type — resolve ``providers.<name>.consumption_type`` with defaults.
    resolve_auth_mode — resolve ``providers.<name>.auth_mode`` (D1; default ``api_key``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

JsonDict = dict[str, Any]

ProviderAuthMode = Literal["api_key", "oauth"]
"""OpenAI provider auth selector (Codex OAuth plan D1): ``api_key`` (default) or ``oauth``."""


class ProviderEntryConfig(BaseModel):
    """``providers.<name>`` object (D2): credential ref, base URLs, transport."""

    model_config = ConfigDict(extra="allow")

    api_key: str | None = None
    auth_mode: ProviderAuthMode | None = None
    base_url: str | None = None
    openai_base_url: str | None = None
    anthropic_base_url: str | None = None
    transport: str | None = None
    consumption_type: str | None = None


class ProviderModelOverrideConfig(BaseModel):
    """``providers.models.<catalog_id>`` per-model overrides."""

    model_config = ConfigDict(extra="allow")

    provider: str | None = None
    transport: str | None = None


class ProvidersWorkspaceSectionConfig(BaseModel):
    """Typed ``providers`` subtree — arbitrary provider names stay in ``model_extra``."""

    model_config = ConfigDict(extra="allow")

    models: dict[str, ProviderModelOverrideConfig | JsonDict] | None = None
    tier_default: dict[str, str] | None = None
    native_model: dict[str, bool] | None = None
    fallback_chain: dict[str, list[str]] | None = None
    use_main_model_for_all: bool | None = None
    minimax: ProviderEntryConfig | None = None
    openai: ProviderEntryConfig | None = None
    anthropic: ProviderEntryConfig | None = None


def providers_section_dict(
    providers: ProvidersWorkspaceSectionConfig | JsonDict | None,
) -> JsonDict:
    """Return a plain ``providers`` mapping for accessors and resolution.

    Args:
        providers (ProvidersWorkspaceSectionConfig | JsonDict | None): Parsed or raw block.

    Returns:
        JsonDict: Merged mapping including ``model_extra`` provider names.

    Examples:
        >>> providers_section_dict(None)
        {}
        >>> providers_section_dict({"tier_default": {"triager": "m"}})
        {'tier_default': {'triager': 'm'}}
    """
    if providers is None:
        return {}
    if isinstance(providers, dict):
        return dict(providers)
    dumped = {
        key: value
        for key, value in providers.model_dump(mode="python").items()
        if value is not None
    }
    extra = getattr(providers, "model_extra", None) or {}
    merged = dict(dumped)
    for key, value in extra.items():
        if key not in merged:
            merged[key] = value
    return merged


def provider_entry_dict(
    providers: ProvidersWorkspaceSectionConfig | JsonDict | None,
    name: str,
) -> JsonDict:
    """Return one ``providers.<name>`` entry as a plain mapping.

    Args:
        providers (ProvidersWorkspaceSectionConfig | JsonDict | None): Parsed block.
        name (str): Provider registry key (e.g. ``minimax``, ``openai``).

    Returns:
        JsonDict: Entry sub-keys when present; empty dict when absent.

    Examples:
        >>> provider_entry_dict({"minimax": {"base_url": "https://x"}}, "minimax")
        {'base_url': 'https://x'}
        >>> provider_entry_dict({"minimax": {"base_url": "https://x"}}, "openai")
        {}
    """
    block = providers_section_dict(providers)
    raw = block.get(name)
    if isinstance(raw, ProviderEntryConfig):
        return raw.model_dump(mode="python")
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def resolve_consumption_type(
    providers: ProvidersWorkspaceSectionConfig | JsonDict | None,
    name: str,
) -> str:
    """Resolve ``providers.<name>.consumption_type`` (``api`` or ``subscription``).

    An explicit valid value wins. Otherwise MiniMax defaults to ``subscription``
    (Token Plan, billed by 5-hour / weekly windows, not per-token); every other
    provider defaults to ``api``.

    Args:
        providers (ProvidersWorkspaceSectionConfig | JsonDict | None): Parsed block.
        name (str): Provider registry key (e.g. ``minimax``, ``openai``).

    Returns:
        str: ``"subscription"`` or ``"api"``.

    Examples:
        >>> resolve_consumption_type({"minimax": {}}, "minimax")
        'subscription'
        >>> resolve_consumption_type({"openai": {}}, "openai")
        'api'
        >>> resolve_consumption_type({"minimax": {"consumption_type": "api"}}, "minimax")
        'api'
    """
    entry = provider_entry_dict(providers, name)
    explicit = entry.get("consumption_type")
    if isinstance(explicit, str) and explicit.strip().lower() in ("api", "subscription"):
        return explicit.strip().lower()
    return "subscription" if name == "minimax" else "api"


def resolve_auth_mode(
    providers: ProvidersWorkspaceSectionConfig | JsonDict | None,
    name: str,
) -> ProviderAuthMode:
    """Resolve ``providers.<name>.auth_mode`` (D1; default ``api_key`` for back-compat D4).

    Args:
        providers (ProvidersWorkspaceSectionConfig | JsonDict | None): Parsed block.
        name (str): Provider registry key (e.g. ``openai``).

    Returns:
        ProviderAuthMode: ``api_key`` or ``oauth``.

    Examples:
        >>> resolve_auth_mode({"openai": {}}, "openai")
        'api_key'
        >>> resolve_auth_mode({"openai": {"auth_mode": "oauth"}}, "openai")
        'oauth'
    """
    entry = provider_entry_dict(providers, name)
    explicit = entry.get("auth_mode")
    if not isinstance(explicit, str):
        return "api_key"
    normalized = explicit.strip().lower()
    if normalized == "oauth":
        return "oauth"
    if normalized == "api_key":
        return "api_key"
    return "api_key"
