"""Opt-in gate for bundled ``cursor_cloud`` core skill (`specs/29-cursor-cloud-agent.md`).

Module: sevn.skills.cursor_cloud
Depends: sevn.config.workspace_config

Exports:
    cursor_cloud_config_enabled — Read ``skills.cursor_cloud.enabled``.
    gate_cursor_cloud_core_skill — Skip or load bundled core skill.
"""

from __future__ import annotations

from typing import Literal

from sevn.config.workspace_config import WorkspaceConfig

CURSOR_CLOUD_SKILL_ID: str = "cursor_cloud"


def cursor_cloud_config_enabled(cfg: WorkspaceConfig | None) -> bool:
    """Return whether ``skills.cursor_cloud.enabled`` is true.

    Args:
        cfg (WorkspaceConfig | None): Loaded workspace config; ``None`` -> disabled.

    Returns:
        bool: ``True`` when the operator opted in.

    Examples:
        >>> cursor_cloud_config_enabled(None)
        False
    """
    if cfg is None or cfg.skills is None:
        return False
    block = cfg.skills.get("cursor_cloud")
    return isinstance(block, dict) and bool(block.get("enabled", False))


def gate_cursor_cloud_core_skill(cfg: WorkspaceConfig | None) -> Literal["skip", "load"]:
    """Decide whether the bundled ``cursor_cloud`` core skill should load.

    Args:
        cfg (WorkspaceConfig | None): Workspace config for the active session.

    Returns:
        Literal["skip", "load"]: ``skip`` when disabled.

    Examples:
        >>> gate_cursor_cloud_core_skill(None)
        'skip'
    """
    if not cursor_cloud_config_enabled(cfg):
        return "skip"
    return "load"
