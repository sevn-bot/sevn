"""``skills.social_media_manager`` subtree models (platform medium config).

Module: sevn.config.sections.skills_social_media
Depends: pydantic

Exports:
    TwexApiSkillBlock — ``twexapi.{enabled,api_key,base_url}`` block.
    PlatformMediumConfig — ``platforms.<site>.medium`` entry.
    SocialMediaManagerSkillConfig — full ``skills.social_media_manager`` block.
    social_media_manager_settings — effective settings accessor.
    social_media_manager_block_dict — plain dict for resolver helpers.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sevn.config.sections.root import WorkspaceConfig  # noqa: TC001

SocialMedium = Literal["browser", "twexapi"]
SiteKey = Literal["x", "facebook", "instagram", "linkedin", "reddit", "tiktok"]

# Mirror ``social.py`` ``_SUPPORTED_SITES`` — equality asserted in tests (D6).
SUPPORTED_SITE_KEYS: frozenset[str] = frozenset(
    {"x", "facebook", "instagram", "linkedin", "reddit", "tiktok"},
)


class TwexApiSkillBlock(BaseModel):
    """``skills.social_media_manager.twexapi`` block (X-only REST medium; D13)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    api_key: str | None = None
    base_url: str | None = None


class PlatformMediumConfig(BaseModel):
    """Per-site medium override under ``skills.social_media_manager.platforms``."""

    model_config = ConfigDict(extra="allow")

    medium: SocialMedium | None = None


class SocialMediaManagerSkillConfig(BaseModel):
    """``skills.social_media_manager`` operator settings (D1/D2/D6)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    default_medium: SocialMedium = "browser"
    twexapi: TwexApiSkillBlock = Field(default_factory=TwexApiSkillBlock)
    platforms: dict[str, PlatformMediumConfig] = Field(default_factory=dict)

    @field_validator("platforms")
    @classmethod
    def _validate_platform_site_keys(
        cls,
        value: dict[str, PlatformMediumConfig],
    ) -> dict[str, PlatformMediumConfig]:
        """Reject platform keys outside ``social.py`` ``_SUPPORTED_SITES`` (D6).

        Args:
            cls (type): Pydantic model class.
            value (dict[str, PlatformMediumConfig]): Raw ``platforms`` mapping.

        Returns:
            dict[str, PlatformMediumConfig]: Validated mapping.

        Raises:
            ValueError: When a site key is not in the SSOT set.

        Examples:
            >>> SocialMediaManagerSkillConfig.model_validate({"platforms": {"x": {}}}).platforms
            {'x': PlatformMediumConfig(medium=None)}
        """
        unknown = set(value.keys()) - SUPPORTED_SITE_KEYS
        if unknown:
            joined = ", ".join(sorted(unknown))
            msg = f"unknown platform site key(s): {joined}"
            raise ValueError(msg)
        return value


def social_media_manager_settings(
    cfg: WorkspaceConfig | None,
) -> SocialMediaManagerSkillConfig:
    """Return effective ``skills.social_media_manager.*`` settings.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        SocialMediaManagerSkillConfig: Defaults when the section is absent.

    Examples:
        >>> social_media_manager_settings(None).default_medium
        'browser'
        >>> social_media_manager_settings(WorkspaceConfig.model_validate({
        ...     "schema_version": 1,
        ...     "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...     "skills": {"social_media_manager": {"default_medium": "browser"}},
        ... })).default_medium
        'browser'
    """
    if cfg is None or cfg.skills is None:
        return SocialMediaManagerSkillConfig()
    block = cfg.skills.get("social_media_manager")
    if not isinstance(block, dict):
        return SocialMediaManagerSkillConfig()
    return SocialMediaManagerSkillConfig.model_validate(block)


def social_media_manager_block_dict(cfg: WorkspaceConfig | None) -> dict[str, Any]:
    """Return ``skills.social_media_manager`` as a plain dict for resolver helpers.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        dict[str, Any]: Block mapping or empty dict.

    Examples:
        >>> social_media_manager_block_dict(None)["default_medium"]
        'browser'
    """
    return social_media_manager_settings(cfg).model_dump(mode="python")
