"""Per-platform capabilities matrix for ``social_media_manager`` (D8).

Module: sevn.integrations.social_media.capabilities
Depends: sevn.integrations.social_media.medium, sevn.integrations.social_media.readiness

Exports:
    build_capabilities_matrix — six-site medium matrix with readiness stubs.
    site_skill_hints — site-appropriate bundled skill ids (D7).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sevn.browser.recipes.social import _SUPPORTED_SITES
from sevn.integrations.social_media.medium import allowed_media_for_site, resolve_social_medium
from sevn.integrations.social_media.readiness import (
    build_social_media_readiness_sync,
    platform_readiness_fields,
)
from sevn.integrations.twexapi.client import TWEXAPI_OPS

SOCIAL_MEDIA_MANAGER_SPECIALIST = "social_media_manager"

_SITE_SKILL_HINTS: dict[str, tuple[str, ...]] = {
    "x": ("social_media_manager",),
    "facebook": ("social_media_manager",),
    "linkedin": ("social_media_manager",),
    "instagram": ("browser-harness",),
    "reddit": ("browser-harness", "last30days"),
    "tiktok": ("browser-harness", "yt-dlp"),
}

__all__ = ["SOCIAL_MEDIA_MANAGER_SPECIALIST", "build_capabilities_matrix", "site_skill_hints"]


def site_skill_hints(site: str) -> list[str]:
    """Return site-appropriate bundled skill hints (D7).

    Args:
        site (str): Canonical social site key.

    Returns:
        list[str]: Skill ids relevant to ``site``.

    Examples:
        >>> site_skill_hints("x")
        ['social_media_manager']
    """
    return list(_SITE_SKILL_HINTS.get(site, ("social_media_manager", "browser-harness")))


def build_capabilities_matrix(
    *,
    content_root: Path,
    smm_cfg: dict[str, Any],
    skills: list[str],
    tools: list[str],
    twex_settings: Any,
    workspace_cfg: Any = None,
) -> dict[str, Any]:
    """Build per-platform capabilities payload (D8).

    Args:
        content_root (Path): Workspace content root for readiness probes.
        smm_cfg (dict[str, Any]): ``skills.social_media_manager`` block.
        skills (list[str]): Declared specialist skills.
        tools (list[str]): Declared specialist tools.
        twex_settings (TwexApiSettings): Resolved TwexAPI settings.
        workspace_cfg (Any): Parsed workspace config for profile resolution.

    Returns:
        dict[str, Any]: Capabilities result with ``platforms`` matrix.

    Examples:
        >>> import tempfile
        >>> from sevn.integrations.twexapi.config import TwexApiSettings
        >>> matrix = build_capabilities_matrix(
        ...     content_root=Path(tempfile.mkdtemp()),
        ...     smm_cfg={"default_medium": "browser"},
        ...     skills=["browser"],
        ...     tools=["browser"],
        ...     twex_settings=TwexApiSettings(),
        ... )
        >>> matrix["medium"]
        'capabilities'
    """
    readiness = build_social_media_readiness_sync(content_root, cfg=workspace_cfg)
    browser = readiness["browser"]
    profile_dir = Path(str(browser["profile_dir"]))
    cdp_ok = bool(browser["cdp_reachable"])
    platforms: dict[str, Any] = {}
    for site in sorted(_SUPPORTED_SITES):
        allowed = list(allowed_media_for_site(site))
        effective = resolve_social_medium({}, smm_cfg, site)
        site_skills = [s for s in site_skill_hints(site) if s in skills] or site_skill_hints(site)
        platforms[site] = {
            "allowed_media": allowed,
            "effective_medium": effective,
            "skills": site_skills,
            "tools": tools,
            "readiness": platform_readiness_fields(
                site,
                settings=twex_settings,
                browser=browser,
                profile_dir=profile_dir,
                cdp_reachable_flag=cdp_ok,
            ),
        }
    return {
        "specialist": SOCIAL_MEDIA_MANAGER_SPECIALIST,
        "medium": "capabilities",
        "skills": skills,
        "tools": tools,
        "platforms": platforms,
        "note": (
            "Per-platform medium matrix (D8). TwexAPI runs inline on X when "
            "effective_medium is twexapi; browser medium returns a CDP plan."
        ),
        "twexapi": {
            "docs": twex_settings.docs_url,
            "base_url": twex_settings.base_url,
            "enabled": twex_settings.enabled,
            "ops": sorted(TWEXAPI_OPS),
        },
    }
