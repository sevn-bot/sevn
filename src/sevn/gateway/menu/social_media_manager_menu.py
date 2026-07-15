"""Telegram ``/config → Skills → Social Media Manager`` menu (W3 / D9).

Module: sevn.gateway.menu.social_media_manager_menu
Depends: sevn.config.sections.skills_social_media, sevn.integrations.social_media.medium

Exports:
    build_social_media_manager_keyboard_rows — inline keyboard rows.
    social_media_manager_menu_caption — section caption text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sevn.browser.recipes.social import _SUPPORTED_SITES
from sevn.config.sections.skills_social_media import (
    social_media_manager_block_dict,
    social_media_manager_settings,
)
from sevn.config.workspace_config import WorkspaceConfig
from sevn.integrations.social_media.medium import allowed_media_for_site, resolve_social_medium
from sevn.integrations.social_media.readiness import (
    format_browser_session_hint,
    twexapi_key_configured,
)
from sevn.integrations.twexapi.config import (
    DEFAULT_TWEXAPI_BASE_URL,
    TWEXAPI_SECRET_ALIAS,
    TwexApiSettings,
)

SMM_CYCLE_PREFIX = "cfg:cycle:skills.social_media_manager"

_SITE_LABELS: dict[str, str] = {
    "x": "X",
    "facebook": "Facebook",
    "instagram": "Instagram",
    "linkedin": "LinkedIn",
    "reddit": "Reddit",
    "tiktok": "TikTok",
}

__all__ = [
    "build_social_media_manager_keyboard_rows",
    "social_media_manager_menu_caption",
]


def _smm_block_dict(workspace: WorkspaceConfig) -> dict[str, Any]:
    """Return ``skills.social_media_manager`` as a plain dict for resolver helpers.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        dict[str, Any]: Block mapping or empty dict.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _smm_block_dict(WorkspaceConfig.minimal())["default_medium"]
        'browser'
    """
    return social_media_manager_block_dict(workspace)


def _effective_medium(workspace: WorkspaceConfig, site: str) -> str:
    """Resolve display medium for one site (no task override).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        site (str): Canonical platform site key.

    Returns:
        str: ``browser`` or ``twexapi`` after D2/D3 rules.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _effective_medium(WorkspaceConfig.minimal(), "facebook")
        'browser'
    """
    return resolve_social_medium({}, _smm_block_dict(workspace), site)


def _cycle_row_for_path(
    *,
    label: str,
    dotted_suffix: str,
    current: str,
    options: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Build a cycle row under ``skills.social_media_manager.*``.

    Args:
        label (str): Button label.
        dotted_suffix (str): Path suffix after ``skills.social_media_manager.``.
        current (str): Current value.
        options (tuple[str, ...]): Allowed values.

    Returns:
        list[dict[str, Any]]: Single-button row.

    Examples:
        >>> row = _cycle_row_for_path(
        ...     label="Default",
        ...     dotted_suffix="default_medium",
        ...     current="browser",
        ...     options=("browser", "twexapi"),
        ... )
        >>> "default_medium" in row[0]["callback_data"]
        True
    """
    if not options:
        options = ("browser",)
    try:
        idx = options.index(current)
    except ValueError:
        idx = 0
    nxt = options[(idx + 1) % len(options)]
    return [
        {
            "text": f"{label}: {current} (→{nxt})",
            "callback_data": f"{SMM_CYCLE_PREFIX}.{dotted_suffix}:{nxt}",
        },
    ]


def _platform_medium(workspace: WorkspaceConfig, site: str) -> str:
    """Return stored platform medium or inherited default for menu display.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        site (str): Platform site key.

    Returns:
        str: Stored or inherited medium string.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _platform_medium(WorkspaceConfig.minimal(), "x")
        'browser'
    """
    smm = social_media_manager_settings(workspace)
    platform = smm.platforms.get(site)
    if platform is not None and platform.medium is not None:
        return platform.medium
    return smm.default_medium


def build_social_media_manager_keyboard_rows(
    workspace: WorkspaceConfig,
    content_root: Path | None = None,
) -> list[list[dict[str, Any]]]:
    """Build Social Media Manager section keyboard (cycles, TwexAPI toggle, secret wizard).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        content_root (Path | None): Unused; reserved for readiness hooks (W4).

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = build_social_media_manager_keyboard_rows(WorkspaceConfig.minimal())
        >>> any("default_medium" in btn.get("callback_data", "") for row in rows for btn in row)
        True
    """
    _ = content_root
    smm = social_media_manager_settings(workspace)
    rows: list[list[dict[str, Any]]] = []

    rows.append(
        _cycle_row_for_path(
            label="Default medium",
            dotted_suffix="default_medium",
            current=smm.default_medium,
            options=("browser", "twexapi"),
        ),
    )

    twex_enabled = smm.twexapi.enabled
    rows.append(
        [
            {
                "text": f"TwexAPI {'✅' if twex_enabled else 'off'}",
                "callback_data": (
                    f"cfg:toggle:skills.social_media_manager.twexapi.enabled:"
                    f"{'false' if twex_enabled else 'true'}"
                ),
            },
        ],
    )
    rows.append(
        [
            {
                "text": f"Set TwexAPI key ({TWEXAPI_SECRET_ALIAS})",
                "callback_data": f"form:secret_wizard:{TWEXAPI_SECRET_ALIAS}",
            },
        ],
    )

    for site in sorted(_SUPPORTED_SITES):
        label = _SITE_LABELS.get(site, site)
        stored = _platform_medium(workspace, site)
        rows.append(
            _cycle_row_for_path(
                label=label,
                dotted_suffix=f"platforms.{site}.medium",
                current=stored,
                options=allowed_media_for_site(site),
            ),
        )

    rows.append([{"text": "⬅ Skills", "callback_data": "cfg:section:skills"}])
    return rows


def social_media_manager_menu_caption(
    workspace: WorkspaceConfig,
    content_root: Path | None = None,
) -> str:
    """Return caption text for ``/config → Skills → Social Media Manager``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        content_root (Path | None): Workspace content root for profile hints.

    Returns:
        str: Plain-text caption (readiness hints; no secret values).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> text = social_media_manager_menu_caption(WorkspaceConfig.minimal())
        >>> "Default medium" in text
        True
    """
    smm = social_media_manager_settings(workspace)
    twex_settings = TwexApiSettings(
        enabled=smm.twexapi.enabled,
        api_key_ref=smm.twexapi.api_key,
        base_url=smm.twexapi.base_url or DEFAULT_TWEXAPI_BASE_URL,
    )
    key_ok = twexapi_key_configured(twex_settings)
    browser_hint = format_browser_session_hint(workspace, content_root)
    lines = [
        "Social Media Manager",
        "",
        f"Default medium: {smm.default_medium}",
        f"TwexAPI enabled: {'yes' if smm.twexapi.enabled else 'no'}",
        f"TwexAPI key configured: {'yes' if key_ok else 'no'}",
        browser_hint,
        "",
        "Effective medium per site:",
    ]
    for site in sorted(_SUPPORTED_SITES):
        label = _SITE_LABELS.get(site, site)
        effective = _effective_medium(workspace, site)
        lines.append(f"  {label}: {effective}")
    return "\n".join(lines)
