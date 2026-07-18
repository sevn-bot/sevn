"""Opt-in gate for bundled Discogs core skills (D3).

Module: sevn.skills.discogs
Depends: sevn.config.sections.skills_discogs

Exports:
    discogs_config_enabled — read ``skills.discogs.enabled``.
    discogs_skill_enabled — per-domain enablement within the group.
    gate_discogs_core_skills — skip or load the Discogs skill group.
"""

from __future__ import annotations

from typing import Literal

from sevn.config.sections.skills_discogs import DISCOGS_DOMAINS, discogs_settings
from sevn.config.workspace_config import WorkspaceConfig

DISCOGS_SKILL_IDS: tuple[str, ...] = tuple(f"discogs-{domain}" for domain in DISCOGS_DOMAINS)

__all__ = [
    "DISCOGS_SKILL_IDS",
    "discogs_config_enabled",
    "discogs_skill_enabled",
    "gate_discogs_core_skills",
]


def discogs_config_enabled(cfg: WorkspaceConfig | None) -> bool:
    """Return whether ``skills.discogs.enabled`` is true.

    Args:
        cfg (WorkspaceConfig | None): Loaded workspace config; ``None`` -> disabled.

    Returns:
        bool: ``True`` when the operator opted in.

    Examples:
        >>> discogs_config_enabled(None)
        False
    """
    return discogs_settings(cfg).enabled


def _domain_for_skill_id(skill_id: str) -> str:
    """Map a bundled skill dir name to its config domain key.

    Args:
        skill_id (str): Bundled skill directory name (e.g. ``discogs-database``).

    Returns:
        str: Domain key (e.g. ``database``).

    Examples:
        >>> _domain_for_skill_id("discogs-database")
        'database'
    """
    return skill_id.removeprefix("discogs-")


def discogs_skill_enabled(cfg: WorkspaceConfig | None, skill_id: str) -> bool:
    """Return whether one Discogs bundled skill should load.

    Args:
        cfg (WorkspaceConfig | None): Workspace config for the active session.
        skill_id (str): Bundled skill directory name (e.g. ``discogs-database``).

    Returns:
        bool: ``False`` when the group or per-skill sub-flag is disabled.

    Examples:
        >>> discogs_skill_enabled(None, "discogs-database")
        False
    """
    settings = discogs_settings(cfg)
    if not settings.enabled:
        return False
    domain = _domain_for_skill_id(skill_id)
    return bool(getattr(settings, f"{domain}_enabled"))


def gate_discogs_core_skills(cfg: WorkspaceConfig | None) -> Literal["skip", "load"]:
    """Decide whether bundled Discogs core skills should load.

    Args:
        cfg (WorkspaceConfig | None): Workspace config for the active session.

    Returns:
        Literal["skip", "load"]: ``skip`` when the group is disabled.

    Examples:
        >>> gate_discogs_core_skills(None)
        'skip'
    """
    if not discogs_config_enabled(cfg):
        return "skip"
    return "load"
