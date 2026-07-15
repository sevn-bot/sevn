"""Validate Telegram ``cfg:cycle`` mutations for social media manager paths.

Module: sevn.integrations.social_media.cycle_validation
Depends: sevn.integrations.social_media.medium, sevn.config.sections.skills_social_media

Exports:
    validate_config_cycle_mutation — reject crafted callbacks outside allowed enums.
"""

from __future__ import annotations

from sevn.config.sections.skills_social_media import SUPPORTED_SITE_KEYS
from sevn.integrations.social_media.medium import allowed_media_for_site

_SOCIAL_MEDIA_MANAGER_PREFIX = "skills.social_media_manager."
_ALLOWED_DEFAULT_MEDIA = frozenset({"browser", "twexapi"})

__all__ = ["validate_config_cycle_mutation"]


def validate_config_cycle_mutation(path: str, value: str) -> bool:
    """Return whether a ``cfg:cycle`` mutation is allowed for *path* / *value*.

    Non-social-media paths pass through (``True``). Social-media paths must use
    allowed medium enums and platform site keys from the SSOT set.

    Args:
        path (str): Dotted ``sevn.json`` path from callback data.
        value (str): Proposed config value.

    Returns:
        bool: ``True`` when the mutation is permitted.

    Examples:
        >>> validate_config_cycle_mutation("skills.social_media_manager.default_medium", "browser")
        True
        >>> validate_config_cycle_mutation("skills.social_media_manager.platforms.facebook.medium", "twexapi")
        False
    """
    if not path.startswith(_SOCIAL_MEDIA_MANAGER_PREFIX):
        return True
    if path == f"{_SOCIAL_MEDIA_MANAGER_PREFIX}default_medium":
        return value in _ALLOWED_DEFAULT_MEDIA
    platform_prefix = f"{_SOCIAL_MEDIA_MANAGER_PREFIX}platforms."
    if path.startswith(platform_prefix) and path.endswith(".medium"):
        site = path.removeprefix(platform_prefix).removesuffix(".medium")
        if site not in SUPPORTED_SITE_KEYS:
            return False
        return value in allowed_media_for_site(site)
    return False
