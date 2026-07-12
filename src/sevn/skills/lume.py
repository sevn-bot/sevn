"""Lume VM lifecycle skill gates (`plan/architecture/04b-skills.md` §17b).

Exports:
    lume_config_enabled — Read ``skills.lume.enabled``.
    gate_lume_core_skill — Skip or validate before loading bundled core skill.
    validate_lume_host — Fail fast when opt-in preconditions are not met.
    resolve_lume_command — Resolve ``argv[0]`` for the ``lume`` CLI.
"""

from __future__ import annotations

import platform
import shutil
from typing import Any, Literal

from sevn.config.workspace_config import WorkspaceConfig
from sevn.skills.errors import SKILL_VALIDATION, SkillExecutionError

LUME_SKILL_ID: str = "lume"
LUME_BINARY_NAME: str = "lume"
_APPLE_SILICON_MACHINES: frozenset[str] = frozenset({"arm64", "aarch64"})


def _lume_block(cfg: WorkspaceConfig | None) -> dict[str, Any] | None:
    """Return the ``skills.lume`` object from workspace config.

    Args:
        cfg (WorkspaceConfig | None): Loaded workspace config.

    Returns:
        dict[str, Any] | None: The nested lume block, or ``None`` when absent.

    Examples:
        >>> _lume_block(None) is None
        True
    """
    if cfg is None or not isinstance(cfg.skills, dict):
        return None
    block = cfg.skills.get("lume")
    return block if isinstance(block, dict) else None


def lume_config_enabled(cfg: WorkspaceConfig | None) -> bool:
    """Return whether ``skills.lume.enabled`` is true in workspace config.

    Args:
        cfg (WorkspaceConfig | None): Loaded workspace config; ``None`` -> disabled.

    Returns:
        bool: ``True`` when the operator opted in to lume.

    Examples:
        >>> lume_config_enabled(None)
        False
    """
    block = _lume_block(cfg)
    return bool(block and block.get("enabled", False))


def resolve_lume_command(cfg: WorkspaceConfig | None) -> str:
    """Resolve the Lume CLI executable name for VM lifecycle subprocesses.

    Args:
        cfg (WorkspaceConfig | None): Workspace config; optional ``skills.lume.command``.

    Returns:
        str: Executable name or path (defaults to ``lume``).

    Examples:
        >>> resolve_lume_command(None)
        'lume'
    """
    block = _lume_block(cfg)
    if block is not None:
        raw = block.get("command")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return LUME_BINARY_NAME


def validate_lume_host(*, cfg: WorkspaceConfig | None = None) -> None:
    """Fail fast when lume is enabled but the host cannot run VM lifecycle commands.

    Args:
        cfg (WorkspaceConfig | None): Optional workspace config for command override.

    Raises:
        SkillExecutionError: When not macOS Apple Silicon or ``lume`` is missing on PATH.

    Examples:
        >>> resolve_lume_command(None)
        'lume'
    """
    if platform.system() != "Darwin":
        msg = (
            "lume requires macOS (Darwin); set skills.lume.enabled false "
            "or run on a macOS host — see plan/architecture/04b-skills.md §17b"
        )
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    if platform.machine() not in _APPLE_SILICON_MACHINES:
        msg = (
            "lume requires Apple Silicon (arm64); set skills.lume.enabled false "
            "or run on an Apple-Silicon Mac — see plan/architecture/04b-skills.md §17b"
        )
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    command = resolve_lume_command(cfg)
    if shutil.which(command) is None:
        msg = (
            f"lume requires `{command}` on PATH; install via onboarding "
            "(plan/architecture/11-onboarding.md) or upstream install.sh"
        )
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)


def gate_lume_core_skill(cfg: WorkspaceConfig | None) -> Literal["skip", "load"]:
    """Decide whether the bundled ``lume`` core skill should load.

    Args:
        cfg (WorkspaceConfig | None): Workspace config governing opt-in.

    Returns:
        Literal["skip", "load"]: ``skip`` when disabled; ``load`` after host validation.

    Raises:
        SkillExecutionError: When enabled but macOS / Apple Silicon / binary preconditions fail.

    Examples:
        >>> gate_lume_core_skill(None)
        'skip'
    """
    if not lume_config_enabled(cfg):
        return "skip"
    validate_lume_host(cfg=cfg)
    return "load"


__all__ = [
    "LUME_BINARY_NAME",
    "LUME_SKILL_ID",
    "gate_lume_core_skill",
    "lume_config_enabled",
    "resolve_lume_command",
    "validate_lume_host",
]
