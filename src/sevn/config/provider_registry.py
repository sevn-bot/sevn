"""Resolve provider bindings and credentials from workspace config.

Module: sevn.config.provider_registry
Depends: dataclasses, sevn.config.sections.providers, sevn.config.workspace_config

Exports:
    ProviderBinding — typed view of one ``providers.<name>`` entry.
    resolve_provider_for_model_id — catalog id → provider name (D1).
    resolve_provider_binding — ``providers.<name>`` → :class:`ProviderBinding`.
    provider_credential_ref — ``providers.<name>.api_key`` ref or literal.

Examples:
    >>> from sevn.config.provider_registry import ProviderBinding
    >>> b = ProviderBinding(name="minimax", api_key_ref="${SECRET:MM}")
    >>> b.name
    'minimax'
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sevn.config.sections.providers import provider_entry_dict, providers_section_dict

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

_DEFAULT_BARE_ID_PROVIDER = "openai"


@dataclass(frozen=True, slots=True)
class ProviderBinding:
    """One named provider entry from ``sevn.json`` ``providers.<name>`` (D2)."""

    name: str
    api_key_ref: str | None = None
    base_url: str | None = None
    openai_base_url: str | None = None
    anthropic_base_url: str | None = None
    transport: str | None = None


def _non_empty_str(value: object) -> str | None:
    """Return stripped string when *value* is a non-empty string.

    Args:
        value (object): Candidate field value.

    Returns:
        str | None: Stripped string or ``None``.

    Examples:
        >>> _non_empty_str("  sk-x  ")
        'sk-x'
        >>> _non_empty_str("")
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _model_provider_override(providers: dict[str, Any], model_id: str) -> str | None:
    """Read ``providers.models.<id>.provider`` when configured.

    Args:
        providers (dict[str, Any]): Merged ``providers`` block.
        model_id (str): Catalog model id.

    Returns:
        str | None: Override provider name when set.

    Examples:
        >>> _model_provider_override(
        ...     {"models": {"gpt-4o": {"provider": "custom"}}},
        ...     "gpt-4o",
        ... )
        'custom'
    """
    models = providers.get("models")
    if not isinstance(models, dict):
        return None
    override = models.get(model_id)
    if isinstance(override, dict):
        return _non_empty_str(override.get("provider"))
    return None


def resolve_provider_for_model_id(cfg: WorkspaceConfig, model_id: str) -> str:
    """Map a catalog model id to its provider name (D1).

    Prefix before ``/`` wins unless ``providers.models.<id>.provider`` overrides.
    Bare ids (no ``/``) default to ``openai``, except bare MiniMax vendor names
    (``MiniMax-*``) which route to ``minimax``.

    Args:
        cfg (WorkspaceConfig): Parsed workspace config.
        model_id (str): Catalog model id from a slot or request body.

    Returns:
        str: Provider name (e.g. ``minimax``, ``openai``).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal()
        >>> resolve_provider_for_model_id(cfg, "minimax/M2")
        'minimax'
        >>> resolve_provider_for_model_id(cfg, "MiniMax-M3")
        'minimax'
        >>> resolve_provider_for_model_id(cfg, "gpt-4o")
        'openai'
    """
    providers = providers_section_dict(cfg.providers)
    override = _model_provider_override(providers, model_id)
    if override is not None:
        return override
    if "/" in model_id:
        return model_id.split("/", 1)[0]
    # Bare wire names: callers that strip the ``minimax/`` catalog prefix
    # (adapt_request_for_transport → resolve_wire_model_id) send e.g. ``MiniMax-M3``. Route those
    # to MiniMax rather than defaulting to OpenAI (transcript-review-2026-06-22).
    if model_id.strip().lower().startswith("minimax-"):
        return "minimax"
    return _DEFAULT_BARE_ID_PROVIDER


def resolve_provider_binding(cfg: WorkspaceConfig, provider_name: str) -> ProviderBinding:
    """Load one ``providers.<name>`` object as a :class:`ProviderBinding`.

    Args:
        cfg (WorkspaceConfig): Parsed workspace config.
        provider_name (str): Provider registry key (D1 name).

    Returns:
        ProviderBinding: Resolved binding fields from config.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(providers={"minimax": {"base_url": "https://x"}})
        >>> resolve_provider_binding(cfg, "minimax")
        ProviderBinding(name='minimax', api_key_ref=None, base_url='https://x', openai_base_url=None, anthropic_base_url=None, transport=None)
    """
    entry = provider_entry_dict(cfg.providers, provider_name)
    return ProviderBinding(
        name=provider_name,
        api_key_ref=_non_empty_str(entry.get("api_key")),
        base_url=_non_empty_str(entry.get("base_url")),
        openai_base_url=_non_empty_str(entry.get("openai_base_url")),
        anthropic_base_url=_non_empty_str(entry.get("anthropic_base_url")),
        transport=_non_empty_str(entry.get("transport")),
    )


def provider_credential_ref(cfg: WorkspaceConfig, provider_name: str) -> str | None:
    """Return ``providers.<name>.api_key`` as a literal or ``${SECRET:…}`` ref.

    Args:
        cfg (WorkspaceConfig): Parsed workspace config.
        provider_name (str): Provider registry key.

    Returns:
        str | None: Credential ref when configured; ``None`` when absent.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     providers={"openai": {"api_key": "${SECRET:OAI}"}},
        ... )
        >>> provider_credential_ref(cfg, "openai")
        '${SECRET:OAI}'
    """
    return resolve_provider_binding(cfg, provider_name).api_key_ref


__all__ = [
    "ProviderBinding",
    "provider_credential_ref",
    "resolve_provider_binding",
    "resolve_provider_for_model_id",
]
