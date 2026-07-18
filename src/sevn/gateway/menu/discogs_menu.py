"""Telegram ``/config → Skills → Discogs → Setup`` menu (W8 / D18-D19).

Module: sevn.gateway.menu.discogs_menu
Depends: sevn.config.sections.skills_discogs

Exports:
    build_discogs_keyboard_rows — Discogs group section keyboard.
    discogs_menu_caption — Discogs section caption text.
    build_discogs_setup_keyboard_rows — Setup submenu keyboard.
    discogs_setup_caption — Setup submenu caption text.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from sevn.config.sections.skills_discogs import (
    DISCOGS_DOMAINS,
    DiscogsDomain,
    DiscogsSkillsConfig,
    discogs_settings,
)
from sevn.config.workspace_config import WorkspaceConfig

DISCOGS_CYCLE_PREFIX = "cfg:cycle:skills.discogs"
DISCOGS_USER_TOKEN_SECRET_ALIAS = "discogs.user_token"
DISCOGS_CONSUMER_KEY_SECRET_ALIAS = "discogs.consumer_key"
DISCOGS_CONSUMER_SECRET_SECRET_ALIAS = "discogs.consumer_secret"
DISCOGS_OAUTH_TOKEN_SECRET_ALIAS = "discogs.oauth_token"
DISCOGS_OAUTH_TOKEN_SECRET_SECRET_ALIAS = "discogs.oauth_token_secret"
DISCOGS_OAUTH_REQUEST_TOKEN_SECRET_ALIAS = "discogs.oauth_request_token"
DISCOGS_OAUTH_REQUEST_SECRET_SECRET_ALIAS = "discogs.oauth_request_secret"

_DOMAIN_LABELS: dict[DiscogsDomain, str] = {
    "database": "Database",
    "marketplace": "Marketplace",
    "collection": "Collection",
    "wantlist": "Wantlist",
    "identity": "Identity",
}

__all__ = [
    "DISCOGS_CONSUMER_KEY_SECRET_ALIAS",
    "DISCOGS_CONSUMER_SECRET_SECRET_ALIAS",
    "DISCOGS_OAUTH_REQUEST_SECRET_SECRET_ALIAS",
    "DISCOGS_OAUTH_REQUEST_TOKEN_SECRET_ALIAS",
    "DISCOGS_OAUTH_TOKEN_SECRET_ALIAS",
    "DISCOGS_OAUTH_TOKEN_SECRET_SECRET_ALIAS",
    "DISCOGS_USER_TOKEN_SECRET_ALIAS",
    "build_discogs_keyboard_rows",
    "build_discogs_setup_keyboard_rows",
    "discogs_menu_caption",
    "discogs_setup_caption",
]


def _domain_enabled(settings: DiscogsSkillsConfig, domain: DiscogsDomain) -> bool:
    """Return the effective per-skill enable flag for one domain.

    Args:
        settings (DiscogsSkillsConfig): Parsed ``skills.discogs`` block.
        domain (DiscogsDomain): Skill domain key.

    Returns:
        bool: Whether the domain skill is enabled.

    Examples:
        >>> from sevn.config.sections.skills_discogs import discogs_settings
        >>> _domain_enabled(discogs_settings(None), "database")
        False
    """
    return bool(getattr(settings, f"{domain}_enabled"))


def _cycle_row_for_path(
    *,
    label: str,
    dotted_suffix: str,
    current: str,
    options: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Build a cycle row under ``skills.discogs.*``.

    Args:
        label (str): Button label.
        dotted_suffix (str): Path suffix after ``skills.discogs.``.
        current (str): Current value.
        options (tuple[str, ...]): Allowed values.

    Returns:
        list[dict[str, Any]]: Single-button row.

    Examples:
        >>> row = _cycle_row_for_path(
        ...     label="Auth",
        ...     dotted_suffix="auth_method",
        ...     current="user_token",
        ...     options=("user_token", "oauth"),
        ... )
        >>> "auth_method" in row[0]["callback_data"]
        True
    """
    if not options:
        options = ("user_token",)
    try:
        idx = options.index(current)
    except ValueError:
        idx = 0
    nxt = options[(idx + 1) % len(options)]
    return [
        {
            "text": f"{label}: {current} (→{nxt})",
            "callback_data": f"{DISCOGS_CYCLE_PREFIX}.{dotted_suffix}:{nxt}",
        },
    ]


def _discogs_extra_installed() -> bool:
    """Return whether the optional ``discogs`` extra is importable.

    Returns:
        bool: ``True`` when ``discogs_client`` is on ``sys.path``.

    Examples:
        >>> isinstance(_discogs_extra_installed(), bool)
        True
    """
    return importlib.util.find_spec("discogs_client") is not None


def _secret_ref_configured(ref: str | None) -> bool:
    """Return whether a credential ref is present in config (no value expansion).

    Args:
        ref (str | None): Literal or ``${SECRET:…}`` reference from config.

    Returns:
        bool: ``True`` when a non-empty ref is configured.

    Examples:
        >>> _secret_ref_configured("${SECRET:discogs.user_token}")
        True
        >>> _secret_ref_configured(None)
        False
    """
    return bool(isinstance(ref, str) and ref.strip())


def build_discogs_keyboard_rows(
    workspace: WorkspaceConfig,
    content_root: Path | None = None,
) -> list[list[dict[str, Any]]]:
    """Build Discogs group keyboard (toggles, auth cycle, Setup entry).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        content_root (Path | None): Unused; reserved for readiness hooks.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = build_discogs_keyboard_rows(WorkspaceConfig.minimal())
        >>> any("skills.discogs.enabled" in btn.get("callback_data", "") for row in rows for btn in row)
        True
    """
    _ = content_root
    settings = discogs_settings(workspace)
    rows: list[list[dict[str, Any]]] = []

    group_enabled = settings.enabled
    rows.append(
        [
            {
                "text": f"Discogs group {'✅' if group_enabled else 'off'}",
                "callback_data": (
                    f"cfg:toggle:skills.discogs.enabled:{'false' if group_enabled else 'true'}"
                ),
            },
        ],
    )

    for domain in DISCOGS_DOMAINS:
        label = _DOMAIN_LABELS.get(domain, domain)
        enabled = _domain_enabled(settings, domain)
        rows.append(
            [
                {
                    "text": f"{label} {'✅' if enabled else 'off'}",
                    "callback_data": (
                        f"cfg:toggle:skills.discogs.{domain}.enabled:"
                        f"{'false' if enabled else 'true'}"
                    ),
                },
            ],
        )

    rows.append(
        _cycle_row_for_path(
            label="Auth method",
            dotted_suffix="auth_method",
            current=settings.auth_method,
            options=("user_token", "oauth"),
        ),
    )
    confirm_writes = settings.confirm_writes
    rows.append(
        [
            {
                "text": f"Confirm writes {'✅' if confirm_writes else 'off'}",
                "callback_data": (
                    f"cfg:toggle:skills.discogs.confirm_writes:"
                    f"{'false' if confirm_writes else 'true'}"
                ),
            },
        ],
    )
    rows.append([{"text": "⚙ Setup", "callback_data": "cfg:section:skills:discogs:setup"}])
    rows.append([{"text": "⬅ Skills", "callback_data": "cfg:section:skills"}])
    return rows


def build_discogs_setup_keyboard_rows(
    workspace: WorkspaceConfig,
    content_root: Path | None = None,
) -> list[list[dict[str, Any]]]:
    """Build Discogs Setup keyboard (user-token wizard, OAuth flow, whoami).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        content_root (Path | None): Unused; reserved for readiness hooks.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = build_discogs_setup_keyboard_rows(WorkspaceConfig.minimal())
        >>> "form:secret_wizard:discogs.user_token" in [
        ...     btn["callback_data"] for row in rows for btn in row
        ... ]
        True
    """
    _ = content_root
    rows: list[list[dict[str, Any]]] = [
        [
            {
                "text": f"User-token ({DISCOGS_USER_TOKEN_SECRET_ALIAS})",
                "callback_data": f"form:secret_wizard:{DISCOGS_USER_TOKEN_SECRET_ALIAS}",
            },
        ],
        [
            {
                "text": "OAuth 1.0a (Setup)",
                "callback_data": "form:discogs:oauth_start",
            },
        ],
        [{"text": "Test connection", "callback_data": "act:discogs:whoami"}],
        [{"text": "⬅ Discogs", "callback_data": "cfg:section:skills:discogs"}],
    ]
    return rows


def discogs_menu_caption(
    workspace: WorkspaceConfig,
    content_root: Path | None = None,
) -> str:
    """Return caption text for ``/config → Skills → Discogs``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        content_root (Path | None): Unused; reserved for readiness hooks.

    Returns:
        str: Plain-text caption (readiness hints; no secret values).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> "Discogs" in discogs_menu_caption(WorkspaceConfig.minimal())
        True
    """
    _ = content_root
    settings = discogs_settings(workspace)
    extra_ok = _discogs_extra_installed()
    lines = [
        "Discogs",
        "",
        f"Group enabled: {'yes' if settings.enabled else 'no'}",
        f"Auth method: {settings.auth_method}",
        f"Confirm writes: {'yes' if settings.confirm_writes else 'no'}",
        f"python3-discogs-client installed: {'yes' if extra_ok else 'no (uv sync --extra discogs)'}",
        "",
        "Per-skill toggles:",
    ]
    for domain in DISCOGS_DOMAINS:
        label = _DOMAIN_LABELS.get(domain, domain)
        state = "on" if _domain_enabled(settings, domain) else "off"
        lines.append(f"  {label}: {state}")
    lines.append("")
    lines.append("Use Setup to store a user token or complete OAuth authorization.")
    return "\n".join(lines)


def discogs_setup_caption(
    workspace: WorkspaceConfig,
    content_root: Path | None = None,
) -> str:
    """Return caption text for ``/config → Skills → Discogs → Setup``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        content_root (Path | None): Unused; reserved for readiness hooks.

    Returns:
        str: Plain-text caption listing configured credential refs (no values).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> "Setup" in discogs_setup_caption(WorkspaceConfig.minimal())
        True
    """
    _ = content_root
    settings = discogs_settings(workspace)
    extra_ok = _discogs_extra_installed()
    lines = [
        "Discogs Setup",
        "",
        f"Auth method: {settings.auth_method}",
        f"Discogs extra installed: {'yes' if extra_ok else 'no'}",
        "",
        "Configured credential refs (values never shown):",
        f"  user_token: {'yes' if _secret_ref_configured(settings.user_token) else 'no'}",
        f"  consumer_key: {'yes' if _secret_ref_configured(settings.consumer_key) else 'no'}",
        f"  consumer_secret: {'yes' if _secret_ref_configured(settings.consumer_secret) else 'no'}",
        f"  oauth_token: {'yes' if _secret_ref_configured(settings.oauth_token) else 'no'}",
        f"  oauth_token_secret: {'yes' if _secret_ref_configured(settings.oauth_token_secret) else 'no'}",
        "",
        "Paste a Discogs user token or complete OAuth, then run Test connection.",
    ]
    return "\n".join(lines)
