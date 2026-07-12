"""Opt-in gate for bundled ``openwiki`` core skill.

Module: sevn.skills.openwiki
Depends: sevn.config.workspace_config

Exports:
    openwiki_config_enabled — Read ``skills.openwiki.enabled``.
    gate_openwiki_core_skill — Skip or load bundled core skill.
"""

from __future__ import annotations

from typing import Literal

from sevn.config.workspace_config import WorkspaceConfig

OPENWIKI_SKILL_ID: str = "openwiki"


def openwiki_config_enabled(cfg: WorkspaceConfig | None) -> bool:
    """Return whether ``skills.openwiki.enabled`` is true.

    Args:
        cfg (WorkspaceConfig | None): Loaded workspace config; ``None`` -> disabled.

    Returns:
        bool: ``True`` when the operator opted in.

    Examples:
        >>> openwiki_config_enabled(None)
        False
    """
    if cfg is None or cfg.skills is None:
        return False
    block = cfg.skills.get("openwiki")
    return isinstance(block, dict) and bool(block.get("enabled", False))


def gate_openwiki_core_skill(cfg: WorkspaceConfig | None) -> Literal["skip", "load"]:
    """Decide whether the bundled ``openwiki`` core skill should load.

    Args:
        cfg (WorkspaceConfig | None): Workspace config for the active session.

    Returns:
        Literal["skip", "load"]: ``skip`` when disabled.

    Examples:
        >>> gate_openwiki_core_skill(None)
        'skip'
    """
    if not openwiki_config_enabled(cfg):
        return "skip"
    return "load"
