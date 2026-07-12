"""Validate provider credential coverage for assigned model slots (D7).

Module: sevn.config.provider_credential_validate
Depends: dataclasses, sevn.config.model_resolution, sevn.config.provider_registry,
    sevn.config.sections.providers, sevn.proxy.credentials, sevn.proxy.settings

Exports:
    MissingProviderCredential — one assigned slot with no resolvable credential.
    declared_provider_names — registry keys under ``providers.<name>`` (D2).
    provider_credential_resolvable — whether D3/D4 can authenticate one provider.
    collect_missing_provider_credentials — slots whose provider lacks a credential path.
    collect_unused_declared_providers — declared registry names with no assigned slot.
    validate_provider_credentials — raise ``ValueError`` when any slot is uncovered.
    format_unused_provider_warning — CLI/doctor warning line for one unused provider.

Examples:
    >>> from sevn.config.workspace_config import WorkspaceConfig
    >>> cfg = WorkspaceConfig.minimal(
    ...     providers={
    ...         "tier_default": {"triager": "openai/gpt-4o"},
    ...         "openai": {"api_key": "${SECRET:OAI}"},
    ...     },
    ... )
    >>> collect_missing_provider_credentials(cfg)
    []
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sevn.config.model_resolution import (
    ModelSlot,
    is_minimax_catalog_model,
    resolve_model_slot,
    resolve_transport_for_model_id,
)
from sevn.config.provider_registry import (
    provider_credential_ref,
    resolve_provider_for_model_id,
)
from sevn.config.sections.providers import providers_section_dict, resolve_auth_mode
from sevn.proxy.credentials import _ANTHROPIC_ROUTE, _OPENAI_CHAT_ROUTE
from sevn.proxy.settings import ProxySettings

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

_PROVIDERS_META_KEYS = frozenset(
    {"tier_default", "models", "native_model", "fallback_chain", "use_main_model_for_all"}
)


def _slot_model_id(cfg: WorkspaceConfig, slot: ModelSlot) -> str | None:
    """Return a stripped model id for one slot when resolvable.

    Args:
        cfg (WorkspaceConfig): Parsed workspace config.
        slot (ModelSlot): Target slot.

    Returns:
        str | None: Resolved catalog id, or ``None`` when the slot cannot be read.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     providers={"tier_default": {"triager": "openai/gpt-4o"}},
        ... )
        >>> _slot_model_id(cfg, ModelSlot.triager)
        'openai/gpt-4o'
    """
    try:
        model_id = resolve_model_slot(cfg, slot)
    except Exception:
        return None
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    return model_id.strip()


@dataclass(frozen=True, slots=True)
class MissingProviderCredential:
    """One assigned slot whose provider has no resolvable credential (D7)."""

    slot: str
    model_id: str
    provider_name: str


def _route_for_transport(transport: str) -> str:
    """Map a transport label to the proxy route used for bucket fallback checks.

    Args:
        transport (str): Lowercased transport from ``resolve_transport_for_model_id``.

    Returns:
        str: Proxy path used for legacy bucket resolution.

    Examples:
        >>> _route_for_transport("anthropic")
        '/llm/anthropic/messages'
        >>> _route_for_transport("chat_completions")
        '/llm/openai/chat/completions'
    """
    if transport == "anthropic":
        return _ANTHROPIC_ROUTE
    return _OPENAI_CHAT_ROUTE


def _legacy_route_key(settings: ProxySettings, route: str, model_id: str) -> str | None:
    """Return today's route-bucket key with MiniMax cross-fallback (D4).

    Args:
        settings (ProxySettings): Env-backed proxy settings.
        route (str): Proxy path.
        model_id (str): Catalog model id for the slot.

    Returns:
        str | None: Legacy bucket key when configured.

    Examples:
        >>> s = ProxySettings(anthropic_api_key="sk-a")
        >>> _legacy_route_key(s, _ANTHROPIC_ROUTE, "anthropic/claude")
        'sk-a'
    """
    is_minimax = is_minimax_catalog_model(model_id)
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


def _provider_binding_configured(cfg: WorkspaceConfig, provider_name: str) -> bool:
    """Return True when ``providers.<name>.api_key`` is declared in ``sevn.json``.

    Args:
        cfg (WorkspaceConfig): Parsed workspace config.
        provider_name (str): Provider registry key.

    Returns:
        bool: Whether a non-empty binding ref or literal is configured.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     providers={"openai": {"api_key": "${SECRET:OAI}"}},
        ... )
        >>> _provider_binding_configured(cfg, "openai")
        True
        >>> _provider_binding_configured(cfg, "minimax")
        False
    """
    ref = provider_credential_ref(cfg, provider_name)
    return bool(ref and ref.strip())


def provider_credential_resolvable(
    cfg: WorkspaceConfig,
    *,
    provider_name: str,
    model_id: str,
) -> bool:
    """Return True when D3/D4 can resolve a credential for one provider + model.

    A non-empty ``providers.<name>.api_key`` in ``sevn.json`` counts as configured.
    Otherwise env route buckets (``OPENAI_API_KEY`` / ``ANTHROPIC_API_KEY``) are checked.

    Args:
        cfg (WorkspaceConfig): Parsed workspace config.
        provider_name (str): Provider registry key (D1).
        model_id (str): Catalog model id assigned to a slot.

    Returns:
        bool: Whether validation should treat the provider as credentialed.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     providers={"openai": {"api_key": "${SECRET:OAI}"}},
        ... )
        >>> provider_credential_resolvable(
        ...     cfg,
        ...     provider_name="openai",
        ...     model_id="openai/gpt-4o",
        ... )
        True
    """
    if _provider_binding_configured(cfg, provider_name):
        return True
    settings = ProxySettings()
    providers_obj = providers_section_dict(cfg.providers)
    transport = resolve_transport_for_model_id(providers_obj, model_id)
    route = _route_for_transport(transport)
    return bool(_legacy_route_key(settings, route, model_id))


def declared_provider_names(cfg: WorkspaceConfig) -> frozenset[str]:
    """Return registry provider names declared under ``providers.<name>`` (D2).

    Args:
        cfg (WorkspaceConfig): Parsed workspace config.

    Returns:
        frozenset[str]: Provider keys excluding tier/model metadata blocks.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     providers={
        ...         "tier_default": {"triager": "m"},
        ...         "openai": {"api_key": "x"},
        ...         "unused_vendor": {"api_key": "y"},
        ...     },
        ... )
        >>> declared_provider_names(cfg) == frozenset({"openai", "unused_vendor"})
        True
    """
    block = providers_section_dict(cfg.providers)
    names: set[str] = set()
    for key, value in block.items():
        if key in _PROVIDERS_META_KEYS:
            continue
        if isinstance(value, dict):
            names.add(str(key))
    return frozenset(names)


def _assigned_provider_names(cfg: WorkspaceConfig) -> frozenset[str]:
    """Return provider names referenced by assigned model slots.

    Args:
        cfg (WorkspaceConfig): Parsed workspace config.

    Returns:
        frozenset[str]: Unique provider registry names (D1).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     providers={"tier_default": {"triager": "openai/gpt-4o"}},
        ... )
        >>> _assigned_provider_names(cfg) == frozenset({"openai"})
        True
    """
    names: set[str] = set()
    for slot in ModelSlot:
        model_id = _slot_model_id(cfg, slot)
        if model_id is None:
            continue
        names.add(resolve_provider_for_model_id(cfg, model_id))
    return frozenset(names)


def _should_enforce_provider_binding(
    cfg: WorkspaceConfig,
    provider_name: str,
    *,
    assigned_providers: frozenset[str],
) -> bool:
    """Return whether D7 should require an explicit credential for one provider.

    Stub providers (``test/*`` catalog ids) skip enforcement. All other assigned
    providers require ``providers.<name>.api_key`` or route-bucket env vars.

    Args:
        cfg (WorkspaceConfig): Parsed workspace config.
        provider_name (str): Provider registry key.
        assigned_providers (frozenset[str]): Providers referenced by model slots.

    Returns:
        bool: Whether to flag the provider when no credential path is configured.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     providers={
        ...         "tier_default": {"triager": "minimax/M2"},
        ...         "minimax": {"base_url": "https://x"},
        ...     },
        ... )
        >>> _should_enforce_provider_binding(
        ...     cfg,
        ...     "minimax",
        ...     assigned_providers=frozenset({"minimax"}),
        ... )
        True
    """
    if provider_name == "test":
        return False
    return provider_name in assigned_providers


def collect_missing_provider_credentials(cfg: WorkspaceConfig) -> list[MissingProviderCredential]:
    """List assigned slots whose provider has no resolvable credential (D7).

    Args:
        cfg (WorkspaceConfig): Parsed workspace config.

    Returns:
        list[MissingProviderCredential]: Uncovered slot rows in ``ModelSlot`` order.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     providers={
        ...         "tier_default": {"triager": "minimax/M2"},
        ...         "minimax": {"base_url": "https://api.minimax.io/anthropic/v1"},
        ...     },
        ... )
        >>> collect_missing_provider_credentials(cfg)[0].provider_name
        'minimax'
    """
    missing: list[MissingProviderCredential] = []
    seen: set[tuple[str, str]] = set()
    assigned_providers = _assigned_provider_names(cfg)
    for slot in ModelSlot:
        model_id = _slot_model_id(cfg, slot)
        if model_id is None:
            continue
        provider_name = resolve_provider_for_model_id(cfg, model_id)
        key = (slot.value, provider_name)
        if key in seen:
            continue
        seen.add(key)
        if not _should_enforce_provider_binding(
            cfg,
            provider_name,
            assigned_providers=assigned_providers,
        ):
            continue
        if provider_name == "openai" and resolve_auth_mode(cfg.providers, "openai") == "oauth":
            continue
        if provider_credential_resolvable(cfg, provider_name=provider_name, model_id=model_id):
            continue
        missing.append(
            MissingProviderCredential(
                slot=slot.value,
                model_id=model_id,
                provider_name=provider_name,
            ),
        )
    return missing


def collect_unused_declared_providers(cfg: WorkspaceConfig) -> list[str]:
    """Return declared ``providers.<name>`` entries not referenced by any slot (D7).

    Args:
        cfg (WorkspaceConfig): Parsed workspace config.

    Returns:
        list[str]: Sorted unused provider registry names.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     providers={
        ...         "tier_default": {"triager": "openai/gpt-4o"},
        ...         "openai": {"api_key": "${SECRET:OAI}"},
        ...         "unused_vendor": {"api_key": "${SECRET:U}"},
        ...     },
        ... )
        >>> collect_unused_declared_providers(cfg)
        ['unused_vendor']
    """
    from sevn.config.provider_secrets import assigned_provider_names_from_doc

    doc = cfg.model_dump(mode="python")
    assigned = assigned_provider_names_from_doc(doc)
    return sorted(name for name in declared_provider_names(cfg) if name not in assigned)


def validate_provider_credentials(cfg: WorkspaceConfig) -> None:
    """Raise when any assigned slot's provider lacks a resolvable credential (D7).

    Args:
        cfg (WorkspaceConfig): Parsed workspace config.

    Raises:
        ValueError: When at least one assigned slot has no credential path.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     providers={
        ...         "tier_default": {"triager": "openai/gpt-4o"},
        ...         "openai": {"api_key": "${SECRET:OAI}"},
        ...     },
        ... )
        >>> validate_provider_credentials(cfg) is None
        True
    """
    missing = collect_missing_provider_credentials(cfg)
    if not missing:
        return
    row = missing[0]
    msg = (
        f"{row.slot} ({row.model_id}): {row.provider_name} provider credential not configured "
        f"(set providers.{row.provider_name}.api_key or OPENAI_API_KEY / ANTHROPIC_API_KEY env vars)"
    )
    raise ValueError(msg)


def format_unused_provider_warning(provider_name: str) -> str:
    """Return one warning line for a declared-but-unused provider (D7).

    Args:
        provider_name (str): Unused registry name.

    Returns:
        str: Operator-facing warning text.

    Examples:
        >>> "unused" in format_unused_provider_warning("unused_vendor").lower()
        True
        >>> "unused_vendor" in format_unused_provider_warning("unused_vendor")
        True
    """
    return (
        f"warning: unused declared provider {provider_name!r} — no assigned model slot "
        f"references providers.{provider_name}; remove the entry or assign a model"
    )


__all__ = [
    "MissingProviderCredential",
    "collect_missing_provider_credentials",
    "collect_unused_declared_providers",
    "declared_provider_names",
    "format_unused_provider_warning",
    "provider_credential_resolvable",
    "validate_provider_credentials",
]
