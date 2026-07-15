"""Opt-in gate for bundled ``social_media_manager`` core skill (D12).

Module: sevn.skills.social_media_manager
Depends: sevn.config.sections.skills_social_media

Exports:
    social_media_manager_config_enabled — read ``skills.social_media_manager.enabled``.
    gate_social_media_manager_core_skill — skip or load bundled core skill.
"""

from __future__ import annotations

from typing import Literal

from sevn.config.sections.skills_social_media import social_media_manager_settings
from sevn.config.workspace_config import WorkspaceConfig

SOCIAL_MEDIA_MANAGER_SKILL_ID: str = "social_media_manager"

__all__ = [
    "SOCIAL_MEDIA_MANAGER_SKILL_ID",
    "gate_social_media_manager_core_skill",
    "social_media_manager_config_enabled",
]


def social_media_manager_config_enabled(cfg: WorkspaceConfig | None) -> bool:
    """Return whether ``skills.social_media_manager.enabled`` is true.

    Args:
        cfg (WorkspaceConfig | None): Loaded workspace config; ``None`` -> disabled.

    Returns:
        bool: ``True`` when the operator opted in.

    Examples:
        >>> social_media_manager_config_enabled(None)
        False
    """
    return social_media_manager_settings(cfg).enabled


def gate_social_media_manager_core_skill(cfg: WorkspaceConfig | None) -> Literal["skip", "load"]:
    """Decide whether the bundled ``social_media_manager`` core skill should load.

    Args:
        cfg (WorkspaceConfig | None): Workspace config for the active session.

    Returns:
        Literal["skip", "load"]: ``skip`` when disabled.

    Examples:
        >>> gate_social_media_manager_core_skill(None)
        'skip'
    """
    if not social_media_manager_config_enabled(cfg):
        return "skip"
    return "load"
