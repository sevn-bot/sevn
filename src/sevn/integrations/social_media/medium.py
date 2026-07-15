"""Platform medium helpers for ``social_media_manager`` (resolver W1b).

Module: sevn.integrations.social_media.medium
Depends: sevn.browser.recipes.social

Exports:
    allowed_media_for_site — valid media values per platform (D3/D4).
    resolve_social_medium — effective medium resolution (D2/D3).
"""

from __future__ import annotations

from typing import Any, Literal

from sevn.browser.recipes.social import _SUPPORTED_SITES

SocialMedium = Literal["browser", "twexapi"]

__all__ = ["allowed_media_for_site", "resolve_social_medium"]


def allowed_media_for_site(site: str) -> tuple[str, ...]:
    """Return allowed medium values for one platform site key (D3/D4).

    TwexAPI is offered on ``x`` only; every site always includes ``browser``.

    Args:
        site (str): Canonical site key from ``social.py`` ``_SUPPORTED_SITES``.

    Returns:
        tuple[str, ...]: Allowed medium strings for config/menu cycles.

    Raises:
        ValueError: When ``site`` is not in the SSOT set.

    Examples:
        >>> allowed_media_for_site("x")
        ('browser', 'twexapi')
        >>> allowed_media_for_site("facebook")
        ('browser',)
    """
    if site not in _SUPPORTED_SITES:
        msg = f"unknown site: {site}"
        raise ValueError(msg)
    if site == "x":
        return ("browser", "twexapi")
    return ("browser",)


def resolve_social_medium(
    task: dict[str, Any],
    cfg: dict[str, Any],
    site: str,
) -> SocialMedium:
    """Resolve effective medium for a social task (D2 order + D3 coerce).

    Precedence: task ``medium`` override → ``platforms.<site>.medium`` →
    ``default_medium`` → ``browser``. TwexAPI coerces to ``browser`` when
    ``site`` is not ``x``.

    Args:
        task (dict[str, Any]): Parsed task payload (may include ``medium``).
        cfg (dict[str, Any]): ``skills.social_media_manager`` block mapping.
        site (str): Target platform site key.

    Returns:
        SocialMedium: Resolved medium after D2 order and D3 coerce.

    Raises:
        ValueError: When ``site`` is not in the SSOT set.

    Examples:
        >>> resolve_social_medium({"medium": "twexapi"}, {}, "x")
        'twexapi'
        >>> resolve_social_medium({"medium": "twexapi"}, {}, "facebook")
        'browser'
    """
    if site not in _SUPPORTED_SITES:
        msg = f"unknown site: {site}"
        raise ValueError(msg)

    raw_medium = task.get("medium")
    if isinstance(raw_medium, str) and raw_medium.strip():
        medium = raw_medium.strip().lower()
    else:
        platforms = cfg.get("platforms")
        platform_block: dict[str, Any] = {}
        if isinstance(platforms, dict):
            raw_platform = platforms.get(site)
            if isinstance(raw_platform, dict):
                platform_block = raw_platform
        platform_medium = platform_block.get("medium")
        if isinstance(platform_medium, str) and platform_medium.strip():
            medium = platform_medium.strip().lower()
        else:
            default_medium = cfg.get("default_medium")
            if isinstance(default_medium, str) and default_medium.strip():
                medium = default_medium.strip().lower()
            else:
                medium = "browser"

    if medium not in ("browser", "twexapi"):
        medium = "browser"

    if medium == "twexapi" and site != "x":
        return "browser"
    return medium  # type: ignore[return-value]
