"""Canonical provider secret aliases and config binding helpers (D2/D6).

Module: sevn.config.provider_secrets
Depends: sevn.config.provider_registry, sevn.onboarding.export_bundle

Exports:
    provider_secret_alias — secrets-store key ``SEVN_SECRET_{PROVIDER}``.
    provider_credential_ref_for_name — ``${SECRET:…}`` ref for one provider.
    apply_provider_credential_bindings — ensure ``providers.<name>.api_key`` refs in a doc.
    assigned_provider_names_from_doc — provider names referenced by model slots (D1).
    handoff_provider_secret_keys — required store aliases for assigned providers.
    resolve_handoff_secret_alias — store alias for one provider's configured ref.
    migrate_legacy_provider_api_key — copy legacy wizard key to per-provider secrets.

Examples:
    >>> provider_secret_alias("minimax")
    'SEVN_SECRET_MINIMAX'
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from sevn.config.provider_credential_validate import _assigned_provider_names
from sevn.config.provider_registry import provider_credential_ref
from sevn.config.workspace_config import parse_workspace_config

LEGACY_PROVIDER_API_KEY = "SEVN_PROVIDER_API_KEY"  # nosec B105 — migration-only


def provider_secret_alias(provider_name: str) -> str:
    """Return the canonical secrets-store key for one provider API key.

    Args:
        provider_name (str): Provider registry name (e.g. ``minimax``, ``openai``).

    Returns:
        str: Store alias ``SEVN_SECRET_{NAME}`` (uppercase provider segment).

    Examples:
        >>> provider_secret_alias("minimax")
        'SEVN_SECRET_MINIMAX'
        >>> provider_secret_alias("openai")
        'SEVN_SECRET_OPENAI'
    """
    return f"SEVN_SECRET_{provider_name.strip().upper()}"


def provider_credential_ref_for_name(provider_name: str) -> str:
    """Return the ``${SECRET:…}`` ref for ``providers.<name>.api_key``.

    Args:
        provider_name (str): Provider registry name.

    Returns:
        str: Credential reference for ``sevn.json``.

    Examples:
        >>> provider_credential_ref_for_name("minimax")
        '${SECRET:SEVN_SECRET_MINIMAX}'
    """
    return f"${{SECRET:{provider_secret_alias(provider_name)}}}"


def assigned_provider_names_from_doc(config_doc: dict[str, Any]) -> frozenset[str]:
    """Return provider names referenced by assigned model slots in ``config_doc``.

    Args:
        config_doc (dict[str, Any]): Merged or promoted workspace JSON.

    Returns:
        frozenset[str]: Unique provider registry names (D1).

    Examples:
        >>> doc = {
        ...     "schema_version": 1,
        ...     "gateway": {"token": "t"},
        ...     "providers": {
        ...         "use_main_model_for_all": False,
        ...         "tier_default": {"triager": "minimax/M2", "B": "openai/gpt-4o"},
        ...     },
        ... }
        >>> assigned_provider_names_from_doc(doc) == frozenset({"minimax", "openai"})
        True
    """
    try:
        cfg = parse_workspace_config(config_doc)
    except (ValueError, TypeError):
        return frozenset()
    return _assigned_provider_names(cfg)


def apply_provider_credential_bindings(doc: dict[str, Any]) -> None:
    """Ensure each assigned provider has ``providers.<name>.api_key`` when absent.

    Never overwrites an existing non-empty ``api_key`` on the provider entry.

    Args:
        doc (dict[str, Any]): Workspace document (mutated in place).

    Examples:
        >>> d: dict[str, Any] = {
        ...     "schema_version": 1,
        ...     "gateway": {"token": "t"},
        ...     "providers": {"tier_default": {"triager": "minimax/M2"}},
        ... }
        >>> apply_provider_credential_bindings(d)
        >>> d["providers"]["minimax"]["api_key"]
        '${SECRET:SEVN_SECRET_MINIMAX}'
    """
    providers = doc.get("providers")
    if not isinstance(providers, dict):
        providers = {}
        doc["providers"] = providers
    for name in sorted(assigned_provider_names_from_doc(doc)):
        entry = providers.get(name)
        if not isinstance(entry, dict):
            entry = {}
            providers[name] = entry
        existing = entry.get("api_key")
        if isinstance(existing, str) and existing.strip():
            continue
        entry["api_key"] = provider_credential_ref_for_name(name)


def handoff_provider_secret_keys(config_doc: dict[str, Any]) -> frozenset[str]:
    """Return secrets-store aliases required for assigned LLM providers.

    Args:
        config_doc (dict[str, Any]): Post-merge workspace JSON.

    Returns:
        frozenset[str]: ``SEVN_SECRET_*`` keys for each assigned provider.

    Examples:
        >>> handoff_provider_secret_keys(
        ...     {
        ...         "schema_version": 1,
        ...         "gateway": {"token": "t"},
        ...         "providers": {"tier_default": {"triager": "minimax/M2"}},
        ...     }
        ... )
        frozenset({'SEVN_SECRET_MINIMAX'})
    """
    return frozenset(
        provider_secret_alias(name) for name in assigned_provider_names_from_doc(config_doc)
    )


def resolve_handoff_secret_alias(config_doc: dict[str, Any], provider_name: str) -> str:
    """Return the store alias for one provider's credential ref in ``config_doc``.

    Uses the configured ``providers.<name>.api_key`` ref when present; otherwise
    falls back to the canonical ``SEVN_SECRET_{PROVIDER}`` alias.

    Args:
        config_doc (dict[str, Any]): Workspace JSON document.
        provider_name (str): Provider registry name.

    Returns:
        str: Logical secrets-store key to probe.

    Examples:
        >>> resolve_handoff_secret_alias(
        ...     {
        ...         "providers": {
        ...             "minimax": {"api_key": "${SECRET:SEVN_SECRET_MINIMAX}"},
        ...         },
        ...     },
        ...     "minimax",
        ... )
        'SEVN_SECRET_MINIMAX'
    """
    from sevn.config.workspace_config import parse_workspace_config

    try:
        cfg = parse_workspace_config(config_doc)
    except (ValueError, TypeError):
        return provider_secret_alias(provider_name)
    ref = provider_credential_ref(cfg, provider_name)
    if ref and ref.startswith("${SECRET:") and ref.endswith("}"):
        alias = ref[len("${SECRET:") : -1].strip()
        if alias:
            return alias
    return provider_secret_alias(provider_name)


async def migrate_legacy_provider_api_key(
    content_root: Path,
    config_doc: dict[str, Any],
    *,
    section: Any | None = None,
) -> dict[str, bool]:
    """Copy ``SEVN_PROVIDER_API_KEY`` to per-provider ``SEVN_SECRET_*`` aliases when missing.

    Args:
        content_root (Path): Workspace content root.
        config_doc (dict[str, Any]): Workspace JSON used to resolve assigned providers.
        section (Any | None): Parsed ``secrets_backend`` block.

    Returns:
        dict[str, bool]: New store alias → whether a value was written this call.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> asyncio.run(migrate_legacy_provider_api_key(Path("."), {}))
        {}
    """
    from sevn.config.workspace_config import SecretsBackendSectionConfig
    from sevn.onboarding.wizard_credentials import get_wizard_credential
    from sevn.security.secrets.factory import secrets_chain_from_workspace

    legacy = await get_wizard_credential(
        content_root,
        LEGACY_PROVIDER_API_KEY,
        section=section,
    )
    if not legacy or not legacy.strip():
        return {}
    chain = secrets_chain_from_workspace(
        content_root,
        section if section is not None else SecretsBackendSectionConfig(),
    )
    written: dict[str, bool] = {}
    for name in sorted(assigned_provider_names_from_doc(config_doc)):
        alias = provider_secret_alias(name)
        existing = await chain.get_resilient(alias)
        if existing and existing.strip():
            continue
        await chain.set(alias, legacy.strip())
        written[alias] = True
    return written


__all__ = [
    "LEGACY_PROVIDER_API_KEY",
    "apply_provider_credential_bindings",
    "assigned_provider_names_from_doc",
    "handoff_provider_secret_keys",
    "migrate_legacy_provider_api_key",
    "provider_credential_ref_for_name",
    "provider_secret_alias",
    "resolve_handoff_secret_alias",
]
