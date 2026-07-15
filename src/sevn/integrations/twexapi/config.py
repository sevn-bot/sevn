"""Workspace config helpers for TwexAPI (``skills.social_media_manager``).

Module: sevn.integrations.twexapi.config
Depends: sevn.config.loader, sevn.config.workspace_config, sevn.security.secrets.*

Exports:
    TwexApiSettings — resolved TwexAPI defaults from workspace config.
    load_twexapi_settings — parse the skills block.
    resolve_twexapi_api_key — expand API key refs / env / secrets store.
    validate_twexapi_base_url — HTTPS host allowlist for operator base URLs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — runtime workspace root resolution
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from sevn.config.loader import find_sevn_json, load_workspace
from sevn.config.sections.skills_social_media import social_media_manager_block_dict
from sevn.config.workspace_config import WorkspaceConfig  # noqa: TC001
from sevn.security.secrets.cache import ResolvedSecretsCache
from sevn.security.secrets.chain import get_secret_resilient
from sevn.security.secrets.factory import secrets_chain_from_workspace
from sevn.security.secrets.value_expand import EnvUnresolvedError, expand_refs_env_then_secret

if TYPE_CHECKING:
    from sevn.security.secrets.chain import SecretsChain

TWEXAPI_SECRET_ALIAS = "SEVN_SECRET_TWEXAPI"  # nosec B105 — secrets-chain alias, not a password
TWEXAPI_ENV_KEYS: tuple[str, ...] = ("TWEXAPI_API_KEY", "SEVN_TWEXAPI_API_KEY")
DEFAULT_TWEXAPI_BASE_URL = "https://api.twexapi.io"
ALLOWED_TWEXAPI_HOSTS: frozenset[str] = frozenset({"api.twexapi.io"})

__all__ = [
    "ALLOWED_TWEXAPI_HOSTS",
    "DEFAULT_TWEXAPI_BASE_URL",
    "TWEXAPI_ENV_KEYS",
    "TWEXAPI_SECRET_ALIAS",
    "TwexApiSettings",
    "load_twexapi_settings",
    "resolve_twexapi_api_key",
    "validate_twexapi_base_url",
]


@dataclass(frozen=True, slots=True)
class TwexApiSettings:
    """Resolved TwexAPI settings from ``skills.social_media_manager``.

    Attributes:
        enabled (bool): When false, TwexAPI medium is disabled (D13 default false).
        base_url (str): API base URL (default ``https://api.twexapi.io``).
        api_key_ref (str | None): Literal or ``${SECRET:…}`` / ``${ENV:…}`` ref.
        docs_url (str): Operator docs URL.
    """

    enabled: bool = False
    base_url: str = DEFAULT_TWEXAPI_BASE_URL
    api_key_ref: str | None = None
    docs_url: str = "https://docs.twexapi.io/"


def validate_twexapi_base_url(raw: str) -> str:
    """Normalize and validate a TwexAPI base URL against an HTTPS host allowlist.

    Args:
        raw (str): Operator-configured base URL.

    Returns:
        str: Normalized URL without trailing slash.

    Raises:
        ValueError: When the URL is not HTTPS or the host is not allowlisted.

    Examples:
        >>> validate_twexapi_base_url("https://api.twexapi.io/")
        'https://api.twexapi.io'
    """
    url = raw.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        msg = "TwexAPI base_url must be an https URL with a host"
        raise ValueError(msg)
    host = parsed.hostname.lower()
    if host not in ALLOWED_TWEXAPI_HOSTS:
        allowed = ", ".join(sorted(ALLOWED_TWEXAPI_HOSTS))
        msg = f"TwexAPI base_url host {host!r} is not allowlisted ({allowed})"
        raise ValueError(msg)
    return url


def _block_from_config(cfg: WorkspaceConfig | None) -> dict[str, Any]:
    """Return ``skills.social_media_manager`` mapping.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        dict[str, Any]: Block or empty dict.

    Examples:
        >>> _block_from_config(None)["default_medium"]
        'browser'
    """
    return social_media_manager_block_dict(cfg)


def load_twexapi_settings(
    workspace: Path,
) -> tuple[TwexApiSettings, WorkspaceConfig | None]:
    """Load TwexAPI settings for a workspace content root.

    Args:
        workspace (Path): ``SEVN_WORKSPACE`` / content root.

    Returns:
        tuple[TwexApiSettings, WorkspaceConfig | None]: Settings and parsed config.

    Examples:
        >>> from pathlib import Path
        >>> settings, _ = load_twexapi_settings(Path("."))
        >>> settings.docs_url.startswith("https://")
        True
    """
    sevn_json = find_sevn_json(workspace)
    if sevn_json is None:
        return TwexApiSettings(), None
    cfg, _layout = load_workspace(start_dir=workspace)
    block = _block_from_config(cfg)
    twex = block.get("twexapi")
    twex_block = twex if isinstance(twex, dict) else {}
    api_ref = twex_block.get("api_key") or block.get("twexapi_api_key") or block.get("api_key")
    api_key_ref = api_ref.strip() if isinstance(api_ref, str) and api_ref.strip() else None
    base_raw = twex_block.get("base_url") or block.get("twexapi_base_url")
    if isinstance(base_raw, str) and base_raw.strip():
        try:
            base_url = validate_twexapi_base_url(base_raw)
        except ValueError:
            base_url = DEFAULT_TWEXAPI_BASE_URL
    else:
        base_url = DEFAULT_TWEXAPI_BASE_URL
    enabled = twex_block.get("enabled", block.get("twexapi_enabled", False))
    return (
        TwexApiSettings(
            enabled=bool(enabled),
            base_url=base_url,
            api_key_ref=api_key_ref,
            docs_url=str(twex_block.get("docs_url") or "https://docs.twexapi.io/"),
        ),
        cfg,
    )


async def _resolve_plaintext_ref(ref: str, chain: SecretsChain) -> str | None:
    """Expand one credential ref via the workspace secrets chain.

    Args:
        ref (str): Literal or ``${SECRET:…}`` / ``${ENV:…}`` reference.
        chain (SecretsChain): Workspace secrets chain.

    Returns:
        str | None: Resolved plaintext when available.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_resolve_plaintext_ref)
        True
    """
    stripped = ref.strip()
    if not stripped:
        return None
    if not stripped.startswith("${"):
        return stripped
    cache = ResolvedSecretsCache(chain, ttl_seconds=300)
    try:
        expanded = await expand_refs_env_then_secret(stripped, cache)
    except (EnvUnresolvedError, ValueError):
        expanded = stripped
    expanded = expanded.strip()
    if expanded.startswith("${"):
        inner = expanded.removeprefix("${").removesuffix("}").strip()
        if inner.upper().startswith("SECRET:"):
            alias = inner.split(":", 1)[1].strip()
            return await get_secret_resilient(chain, alias)
        return None
    return expanded or None


async def resolve_twexapi_api_key(
    *,
    content_root: Path,
    settings: TwexApiSettings | None = None,
) -> str:
    """Resolve the TwexAPI Bearer token.

    Precedence: configured ``api_key`` ref → ``TWEXAPI_API_KEY`` /
    ``SEVN_TWEXAPI_API_KEY`` env → ``SEVN_SECRET_TWEXAPI`` store alias.

    Args:
        content_root (Path): Workspace content root.
        settings (TwexApiSettings | None): Pre-loaded settings; ``None`` loads them.

    Returns:
        str: Plaintext API key.

    Raises:
        TwexApiError: When no key is configured (imported lazily to avoid cycles).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(resolve_twexapi_api_key)
        True
    """
    from sevn.integrations.twexapi.client import TwexApiError

    resolved_settings = settings
    cfg: WorkspaceConfig | None = None
    if resolved_settings is None:
        resolved_settings, cfg = load_twexapi_settings(content_root)
    if cfg is None:
        cfg, _layout = load_workspace(start_dir=content_root)
    chain = secrets_chain_from_workspace(content_root, cfg.secrets_backend)
    if resolved_settings.api_key_ref:
        plaintext = await _resolve_plaintext_ref(resolved_settings.api_key_ref, chain)
        if plaintext:
            return plaintext
    for env_name in TWEXAPI_ENV_KEYS:
        env_key = os.environ.get(env_name, "").strip()
        if env_key:
            return env_key
    from_store = await get_secret_resilient(chain, TWEXAPI_SECRET_ALIAS)
    if from_store:
        return from_store
    raise TwexApiError(
        "TwexAPI API key missing — set skills.social_media_manager.twexapi.api_key "
        f"or store `{TWEXAPI_SECRET_ALIAS}` / TWEXAPI_API_KEY "
        "(see https://docs.twexapi.io/)",
    )
