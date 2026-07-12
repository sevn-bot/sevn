"""Cua Agent skill gates and per-run approval (`plan/architecture/04b-skills.md` §17a).

Exports:
    cua_agent_config_enabled — Read ``skills.cua_agent.enabled``.
    cua_agent_require_computer_use — Read ``skills.cua_agent.require_computer_use``.
    cua_agent_approval_mode — Read ``skills.cua_agent.approval``.
    gate_cua_agent_core_skill — Skip or validate before loading bundled core skill.
    validate_cua_agent_host — Fail fast when opt-in preconditions are not met.
    validate_cua_agent_run — Enforce per-run operator approval at execution boundary.
"""

from __future__ import annotations

import platform
import shutil
from typing import Any, Literal

from sevn.config.workspace_config import WorkspaceConfig
from sevn.skills.computer_use import computer_use_config_enabled, resolve_cua_cli_command
from sevn.skills.errors import SKILL_VALIDATION, SkillExecutionError

CUA_AGENT_SKILL_ID: str = "cua-agent"
CUA_CLI_BINARY_NAME: str = "cua"
CUA_AGENT_APPROVAL_PER_RUN: str = "per_run"


def _cua_agent_block(cfg: WorkspaceConfig | None) -> dict[str, Any] | None:
    """Return the ``skills.cua_agent`` object from workspace config.

    Args:
        cfg (WorkspaceConfig | None): Loaded workspace config.

    Returns:
        dict[str, Any] | None: The nested cua-agent block, or ``None`` when absent.

    Examples:
        >>> _cua_agent_block(None) is None
        True
    """
    if cfg is None or not isinstance(cfg.skills, dict):
        return None
    block = cfg.skills.get("cua_agent")
    return block if isinstance(block, dict) else None


def cua_agent_config_enabled(cfg: WorkspaceConfig | None) -> bool:
    """Return whether ``skills.cua_agent.enabled`` is true in workspace config.

    Args:
        cfg (WorkspaceConfig | None): Loaded workspace config; ``None`` -> disabled.

    Returns:
        bool: ``True`` when the operator opted in to cua-agent.

    Examples:
        >>> cua_agent_config_enabled(None)
        False
    """
    block = _cua_agent_block(cfg)
    return bool(block and block.get("enabled", False))


def cua_agent_require_computer_use(cfg: WorkspaceConfig | None) -> bool:
    """Return whether cua-agent requires ``computer-use`` to be enabled.

    Args:
        cfg (WorkspaceConfig | None): Loaded workspace config; absent -> ``True``.

    Returns:
        bool: Value of ``skills.cua_agent.require_computer_use``.

    Examples:
        >>> cua_agent_require_computer_use(None)
        True
    """
    block = _cua_agent_block(cfg)
    if block is None:
        return True
    return bool(block.get("require_computer_use", True))


def cua_agent_approval_mode(cfg: WorkspaceConfig | None) -> str:
    """Return the configured autonomous-loop approval mode.

    Args:
        cfg (WorkspaceConfig | None): Loaded workspace config; absent -> ``per_run``.

    Returns:
        str: One of ``per_run`` (HITL before each autonomous run).

    Examples:
        >>> cua_agent_approval_mode(None)
        'per_run'
    """
    block = _cua_agent_block(cfg)
    if block is None:
        return CUA_AGENT_APPROVAL_PER_RUN
    raw = block.get("approval")
    if isinstance(raw, str) and raw.strip() == CUA_AGENT_APPROVAL_PER_RUN:
        return CUA_AGENT_APPROVAL_PER_RUN
    return CUA_AGENT_APPROVAL_PER_RUN


def validate_cua_agent_host(*, cfg: WorkspaceConfig | None = None) -> None:
    """Fail fast when cua-agent is enabled but the host cannot run the autonomous loop.

    Args:
        cfg (WorkspaceConfig | None): Optional workspace config for dependency checks.

    Raises:
        SkillExecutionError: When macOS, ``computer-use``, or ``cua`` preconditions fail.

    Examples:
        >>> resolve_cua_cli_command(None)
        'cua'
    """
    if platform.system() != "Darwin":
        msg = (
            "cua-agent requires macOS (Darwin); set skills.cua_agent.enabled false "
            "or run on a macOS host — see plan/architecture/04b-skills.md §17a"
        )
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    if cua_agent_require_computer_use(cfg) and not computer_use_config_enabled(cfg):
        msg = (
            "cua-agent requires computer-use enabled "
            "(skills.computer_use.enabled true); enable computer-use first or set "
            "skills.cua_agent.require_computer_use false"
        )
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    command = resolve_cua_cli_command(cfg)
    if shutil.which(command) is None:
        msg = (
            f"cua-agent requires `{command}` on PATH; install via `pip install cua` "
            "(plan/architecture/11-onboarding.md)"
        )
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)


def gate_cua_agent_core_skill(cfg: WorkspaceConfig | None) -> Literal["skip", "load"]:
    """Decide whether the bundled ``cua-agent`` core skill should load.

    Args:
        cfg (WorkspaceConfig | None): Workspace config governing opt-in.

    Returns:
        Literal["skip", "load"]: ``skip`` when disabled; ``load`` after host validation.

    Raises:
        SkillExecutionError: When enabled but macOS / binary / computer-use preconditions fail.

    Examples:
        >>> gate_cua_agent_core_skill(None)
        'skip'
    """
    if not cua_agent_config_enabled(cfg):
        return "skip"
    validate_cua_agent_host(cfg=cfg)
    return "load"


def validate_cua_agent_run(*, cfg: WorkspaceConfig | None, approved: bool) -> None:
    """Enforce per-run operator approval before starting the autonomous GUI loop.

    Args:
        cfg (WorkspaceConfig | None): Workspace config governing opt-in and approval mode.
        approved (bool): Whether the operator explicitly approved this run (HITL).

    Raises:
        SkillExecutionError: When disabled, host preconditions fail, or approval is missing.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig(
        ...     schema_version=1,
        ...     skills={
        ...         "cua_agent": {"enabled": True},
        ...         "computer_use": {"enabled": True},
        ...     },
        ...     gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
        ... )
        >>> try:
        ...     validate_cua_agent_run(cfg=cfg, approved=False)
        ... except SkillExecutionError as exc:
        ...     "approval" in str(exc)
        ... else:
        ...     False
        True
    """
    if not cua_agent_config_enabled(cfg):
        msg = "skills.cua_agent.enabled is false"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    if cua_agent_approval_mode(cfg) == CUA_AGENT_APPROVAL_PER_RUN and not approved:
        msg = (
            "cua-agent autonomous loop requires explicit per-run operator approval "
            "(pass --approved after the operator confirms this run)"
        )
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    validate_cua_agent_host(cfg=cfg)


__all__ = [
    "CUA_AGENT_APPROVAL_PER_RUN",
    "CUA_AGENT_SKILL_ID",
    "CUA_CLI_BINARY_NAME",
    "cua_agent_approval_mode",
    "cua_agent_config_enabled",
    "cua_agent_require_computer_use",
    "gate_cua_agent_core_skill",
    "validate_cua_agent_host",
    "validate_cua_agent_run",
]
