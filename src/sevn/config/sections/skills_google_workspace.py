"""``skills.google_workspace`` subtree models.

Module: sevn.config.sections.skills_google_workspace
Depends: pydantic

Exports:
    GoogleWorkspaceServiceSet — valid ``default_services`` values.
    GoogleWorkspaceSkillConfig — full ``skills.google_workspace`` block.
    google_workspace_settings — effective settings accessor.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from sevn.config.sections.root import WorkspaceConfig  # noqa: TC001

GoogleWorkspaceServiceSet = Literal[
    "email",
    "calendar",
    "drive",
    "sheets",
    "docs",
    "contacts",
    "all",
]


class GoogleWorkspaceSkillConfig(BaseModel):
    """``skills.google_workspace`` operator settings."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    prefer_gws: bool = True
    default_services: GoogleWorkspaceServiceSet = "all"
    account_label: str = "Primary Google"
    dry_run: bool = False


def google_workspace_settings(cfg: WorkspaceConfig | None) -> GoogleWorkspaceSkillConfig:
    """Return effective ``skills.google_workspace.*`` settings.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        GoogleWorkspaceSkillConfig: Defaults when the section is absent.

    Examples:
        >>> google_workspace_settings(None).default_services
        'all'
        >>> google_workspace_settings(WorkspaceConfig.model_validate({
        ...     "schema_version": 1,
        ...     "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...     "skills": {"google_workspace": {"account_label": "Work"}},
        ... })).account_label
        'Work'
    """
    if cfg is None or cfg.skills is None:
        return GoogleWorkspaceSkillConfig()
    block = cfg.skills.get("google_workspace")
    if not isinstance(block, dict):
        return GoogleWorkspaceSkillConfig()
    return GoogleWorkspaceSkillConfig.model_validate(block)


__all__ = [
    "GoogleWorkspaceServiceSet",
    "GoogleWorkspaceSkillConfig",
    "google_workspace_settings",
]
