"""Opt-in gate for bundled ``obsidian-cli`` core skill.

Module: sevn.skills.obsidian_cli
Depends: sevn.config.workspace_config

Exports:
    obsidian_cli_config_enabled — Read ``skills.obsidian_cli.enabled``.
    gate_obsidian_cli_core_skill — Skip or load bundled core skill.
"""

from __future__ import annotations

from typing import Literal

from sevn.config.workspace_config import WorkspaceConfig

OBSIDIAN_CLI_SKILL_ID: str = "obsidian-cli"


def obsidian_cli_config_enabled(cfg: WorkspaceConfig | None) -> bool:
    """Return whether ``skills.obsidian_cli.enabled`` is true.

    Args:
        cfg (WorkspaceConfig | None): Loaded workspace config; ``None`` -> disabled.

    Returns:
        bool: ``True`` when the operator opted in.

    Examples:
        >>> obsidian_cli_config_enabled(None)
        False
    """
    if cfg is None or cfg.skills is None:
        return False
    block = cfg.skills.get("obsidian_cli")
    return isinstance(block, dict) and bool(block.get("enabled", False))


def gate_obsidian_cli_core_skill(cfg: WorkspaceConfig | None) -> Literal["skip", "load"]:
    """Decide whether the bundled ``obsidian-cli`` core skill should load.

    Args:
        cfg (WorkspaceConfig | None): Workspace config for the active session.

    Returns:
        Literal["skip", "load"]: ``skip`` when disabled.

    Examples:
        >>> gate_obsidian_cli_core_skill(None)
        'skip'
    """
    if not obsidian_cli_config_enabled(cfg):
        return "skip"
    return "load"
