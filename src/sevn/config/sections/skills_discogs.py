"""``skills.discogs`` subtree models (optional Discogs skill group).

Module: sevn.config.sections.skills_discogs
Depends: pydantic

Exports:
    DiscogsSkillsConfig — full ``skills.discogs`` block.
    discogs_settings — effective settings accessor.
    discogs_block_dict — plain dict for resolver helpers.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sevn.config.sections.root import WorkspaceConfig  # noqa: TC001

DiscogsAuthMethod = Literal["user_token", "oauth"]
DiscogsDomain = Literal["database", "marketplace", "collection", "wantlist", "identity"]

DISCOGS_DOMAINS: tuple[DiscogsDomain, ...] = (
    "database",
    "marketplace",
    "collection",
    "wantlist",
    "identity",
)


class DiscogsSkillsConfig(BaseModel):
    """``skills.discogs`` operator settings (D4)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    enabled: bool = False
    auth_method: DiscogsAuthMethod = "user_token"
    user_agent: str = "sevn-discogs/1.0"
    confirm_writes: bool = True
    user_token: str | None = None
    consumer_key: str | None = None
    consumer_secret: str | None = None
    oauth_token: str | None = None
    oauth_token_secret: str | None = None
    database_enabled: bool = Field(default=True, validation_alias="database.enabled")
    marketplace_enabled: bool = Field(default=True, validation_alias="marketplace.enabled")
    collection_enabled: bool = Field(default=True, validation_alias="collection.enabled")
    wantlist_enabled: bool = Field(default=True, validation_alias="wantlist.enabled")
    identity_enabled: bool = Field(default=True, validation_alias="identity.enabled")

    @model_validator(mode="before")
    @classmethod
    def _default_per_skill_flags(cls, data: object) -> object:
        """Mirror group ``enabled`` into ``<domain>.enabled`` when omitted.

        Args:
            cls (type): Pydantic model class.
            data (object): Raw ``skills.discogs`` block.

        Returns:
            object: Block with defaulted per-skill enable keys.

        Examples:
            >>> DiscogsSkillsConfig.model_validate({"enabled": True}).database_enabled
            True
        """
        if not isinstance(data, dict):
            return data
        block = dict(data)
        group_enabled = bool(block.get("enabled", False))
        for domain in DISCOGS_DOMAINS:
            dotted = f"{domain}.enabled"
            if dotted not in block:
                block[dotted] = group_enabled
        return block


def discogs_settings(cfg: WorkspaceConfig | None) -> DiscogsSkillsConfig:
    """Return effective ``skills.discogs.*`` settings.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        DiscogsSkillsConfig: Defaults when the section is absent.

    Examples:
        >>> discogs_settings(None).enabled
        False
        >>> discogs_settings(None).auth_method
        'user_token'
    """
    if cfg is None or cfg.skills is None:
        return DiscogsSkillsConfig()
    block = cfg.skills.get("discogs")
    if not isinstance(block, dict):
        return DiscogsSkillsConfig()
    return DiscogsSkillsConfig.model_validate(block)


def discogs_block_dict(cfg: WorkspaceConfig | None) -> dict[str, Any]:
    """Return ``skills.discogs`` as a plain dict for resolver helpers.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        dict[str, Any]: Block mapping or empty dict.

    Examples:
        >>> discogs_block_dict(None)["enabled"]
        False
    """
    return discogs_settings(cfg).model_dump(mode="python", by_alias=True)
