"""Computer-use skill gates and Cua Driver MCP passthrough (`plan/architecture/04b-skills.md` §17).

Exports:
    computer_use_config_enabled — Read ``skills.computer_use.enabled``.
    gate_computer_use_core_skill — Skip or validate before loading bundled core skill.
    validate_computer_use_host — Fail fast when opt-in preconditions are not met.
    computer_use_mcp_enabled — Whether gateway should register Cua Driver MCP.
    resolve_computer_use_target — Resolve ``skills.computer_use.target`` (default host).
    resolve_cua_driver_command — Resolve ``argv[0]`` for the stdio MCP server.
    resolve_cua_cli_command — Resolve ``argv[0]`` for the sandbox ``cua`` CLI.
    resolve_cua_do_switch_provider — Provider name for ``cua do switch <provider>``.
    computer_use_uses_cua_driver_mcp — Whether the host MCP backend is active.
    computer_use_snapshot_annotate_enabled — Read ``skills.computer_use.snapshot.annotate``.
    computer_use_trajectory_share_enabled — Read ``skills.computer_use.trajectory.share``.
    computer_use_trajectory_export_dir — Read ``skills.computer_use.trajectory.export_dir``.
    mcp_stdio_entry — Build ``{command, args}`` row or ``None`` when disabled.
    merge_computer_use_mcp_server — Inject stdio registration into a config document.
"""

from __future__ import annotations

import platform
import shutil
from typing import Any, Literal

from sevn.config.workspace_config import WorkspaceConfig
from sevn.skills.errors import SKILL_VALIDATION, SkillExecutionError

COMPUTER_USE_SKILL_ID: str = "computer-use"
CUA_DRIVER_MCP_SERVER_ID: str = "cua-driver"
CUA_DRIVER_BINARY_NAME: str = "cua-driver"
CUA_CLI_BINARY_NAME: str = "cua"
CUA_DRIVER_MCP_ARGS: tuple[str, ...] = ("mcp",)
COMPUTER_USE_TARGET_HOST: str = "host"
COMPUTER_USE_TARGETS: frozenset[str] = frozenset({"host", "docker", "cloud", "lume"})
SANDBOX_COMPUTER_USE_TARGETS: frozenset[str] = frozenset({"docker", "cloud", "lume"})


def _computer_use_block(cfg: WorkspaceConfig | None) -> dict[str, Any] | None:
    """Return the ``skills.computer_use`` object from workspace config.

    Args:
        cfg (WorkspaceConfig | None): Loaded workspace config.

    Returns:
        dict[str, Any] | None: The nested computer-use block, or ``None`` when absent.

    Examples:
        >>> _computer_use_block(None) is None
        True
    """
    if cfg is None or not isinstance(cfg.skills, dict):
        return None
    cu = cfg.skills.get("computer_use")
    return cu if isinstance(cu, dict) else None


def computer_use_config_enabled(cfg: WorkspaceConfig | None) -> bool:
    """Return whether ``skills.computer_use.enabled`` is true in workspace config.

    Args:
        cfg (WorkspaceConfig | None): Loaded workspace config; ``None`` -> disabled.

    Returns:
        bool: ``True`` when the operator opted in to computer-use.

    Examples:
        >>> computer_use_config_enabled(None)
        False
    """
    cu = _computer_use_block(cfg)
    return bool(cu and cu.get("enabled", False))


def resolve_computer_use_target(cfg: WorkspaceConfig | None) -> str:
    """Resolve the active computer-use provider target from workspace config.

    Args:
        cfg (WorkspaceConfig | None): Workspace config; absent key defaults to ``host``.

    Returns:
        str: One of ``host``, ``docker``, ``cloud``, or ``lume``.

    Examples:
        >>> resolve_computer_use_target(None)
        'host'
    """
    cu = _computer_use_block(cfg)
    if cu is None:
        return COMPUTER_USE_TARGET_HOST
    raw = cu.get("target")
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in COMPUTER_USE_TARGETS:
            return normalized
    return COMPUTER_USE_TARGET_HOST


def resolve_cua_driver_command(cfg: WorkspaceConfig | None) -> str:
    """Resolve the Cua Driver executable name for MCP stdio spawn.

    Args:
        cfg (WorkspaceConfig | None): Workspace config; optional ``skills.computer_use.command``.

    Returns:
        str: Executable name or path (defaults to ``cua-driver``).

    Examples:
        >>> resolve_cua_driver_command(None)
        'cua-driver'
    """
    cu = _computer_use_block(cfg)
    if cu is not None:
        raw = cu.get("command")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return CUA_DRIVER_BINARY_NAME


def resolve_cua_cli_command(cfg: WorkspaceConfig | None) -> str:
    """Resolve the sandbox ``cua`` CLI executable for non-host targets.

    Args:
        cfg (WorkspaceConfig | None): Workspace config; optional ``skills.computer_use.command``.

    Returns:
        str: Executable name or path (defaults to ``cua``).

    Examples:
        >>> resolve_cua_cli_command(None)
        'cua'
    """
    cu = _computer_use_block(cfg)
    if cu is not None:
        raw = cu.get("command")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return CUA_CLI_BINARY_NAME


def resolve_cua_do_switch_provider(cfg: WorkspaceConfig | None) -> str:
    """Return the provider argument for ``cua do switch <provider>``.

    Args:
        cfg (WorkspaceConfig | None): Workspace config governing the active target.

    Returns:
        str: Provider name matching ``skills.computer_use.target``.

    Examples:
        >>> resolve_cua_do_switch_provider(None)
        'host'
    """
    return resolve_computer_use_target(cfg)


def computer_use_uses_cua_driver_mcp(cfg: WorkspaceConfig | None) -> bool:
    """Return whether the host ``cua-driver`` MCP backend should be used.

    Args:
        cfg (WorkspaceConfig | None): Workspace config governing the active target.

    Returns:
        bool: ``True`` only when ``target`` is ``host``.

    Examples:
        >>> computer_use_uses_cua_driver_mcp(None)
        True
    """
    return resolve_computer_use_target(cfg) == COMPUTER_USE_TARGET_HOST


def computer_use_snapshot_annotate_enabled(cfg: WorkspaceConfig | None) -> bool:
    """Return whether AI-annotated ``cua do snapshot`` is enabled.

    Args:
        cfg (WorkspaceConfig | None): Workspace config; absent -> ``False``.

    Returns:
        bool: Value of ``skills.computer_use.snapshot.annotate``.

    Examples:
        >>> computer_use_snapshot_annotate_enabled(None)
        False
    """
    cu = _computer_use_block(cfg)
    if cu is None:
        return False
    snapshot = cu.get("snapshot")
    if not isinstance(snapshot, dict):
        return False
    return bool(snapshot.get("annotate", False))


def computer_use_trajectory_share_enabled(cfg: WorkspaceConfig | None) -> bool:
    """Return whether trajectory share is enabled for computer-use sessions.

    Args:
        cfg (WorkspaceConfig | None): Workspace config; absent -> ``True`` (upstream default).

    Returns:
        bool: Value of ``skills.computer_use.trajectory.share``.

    Examples:
        >>> computer_use_trajectory_share_enabled(None)
        True
    """
    cu = _computer_use_block(cfg)
    if cu is None:
        return True
    trajectory = cu.get("trajectory")
    if not isinstance(trajectory, dict):
        return True
    return bool(trajectory.get("share", True))


def computer_use_trajectory_export_dir(cfg: WorkspaceConfig | None) -> str | None:
    """Return the configured trajectory export directory, if any.

    Args:
        cfg (WorkspaceConfig | None): Workspace config.

    Returns:
        str | None: ``skills.computer_use.trajectory.export_dir`` when set.

    Examples:
        >>> computer_use_trajectory_export_dir(None) is None
        True
    """
    cu = _computer_use_block(cfg)
    if cu is None:
        return None
    trajectory = cu.get("trajectory")
    if not isinstance(trajectory, dict):
        return None
    raw = trajectory.get("export_dir")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def validate_computer_use_host(*, cfg: WorkspaceConfig | None = None) -> None:
    """Fail fast when computer-use is enabled but the host cannot run the active backend.

    Args:
        cfg (WorkspaceConfig | None): Optional workspace config for target and command override.

    Raises:
        SkillExecutionError: When the host is not macOS or the required binary is missing.

    Examples:
        >>> resolve_cua_driver_command(None)
        'cua-driver'
    """
    if platform.system() != "Darwin":
        msg = (
            "computer-use requires macOS (Darwin); set skills.computer_use.enabled false "
            "or run on a macOS host — see plan/architecture/04b-skills.md §17"
        )
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    target = resolve_computer_use_target(cfg)
    if computer_use_uses_cua_driver_mcp(cfg):
        command = resolve_cua_driver_command(cfg)
        if shutil.which(command) is None:
            msg = (
                f"computer-use requires `{command}` on PATH; install the Cua Driver via onboarding "
                "(plan/architecture/11-onboarding.md) or upstream install.sh"
            )
            raise SkillExecutionError(msg, code=SKILL_VALIDATION)
        return
    command = resolve_cua_cli_command(cfg)
    if shutil.which(command) is None:
        msg = (
            f"computer-use target `{target}` requires `{command}` on PATH; "
            "install via `pip install cua` (plan/architecture/11-onboarding.md)"
        )
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)


def gate_computer_use_core_skill(cfg: WorkspaceConfig | None) -> Literal["skip", "load"]:
    """Decide whether the bundled ``computer-use`` core skill should load.

    Args:
        cfg (WorkspaceConfig | None): Workspace config governing opt-in.

    Returns:
        Literal["skip", "load"]: ``skip`` when disabled; ``load`` after host validation.

    Raises:
        SkillExecutionError: When enabled but macOS / binary preconditions fail.

    Examples:
        >>> gate_computer_use_core_skill(None)
        'skip'
    """
    if not computer_use_config_enabled(cfg):
        return "skip"
    validate_computer_use_host(cfg=cfg)
    return "load"


def computer_use_mcp_enabled(workspace: WorkspaceConfig) -> bool:
    """Return True when Cua Driver MCP registration should be attempted.

    Host target only — sandbox providers use the ``cua`` CLI instead of MCP passthrough.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.

    Returns:
        bool: ``True`` when enabled with ``target: host``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> computer_use_mcp_enabled(WorkspaceConfig.minimal())
        False
    """
    return computer_use_config_enabled(workspace) and computer_use_uses_cua_driver_mcp(workspace)


def mcp_stdio_entry(workspace: WorkspaceConfig) -> dict[str, str | list[str]] | None:
    """Build an ``mcp_servers`` stdio row for the Cua Driver when opt-in is active.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.

    Returns:
        dict[str, str | list[str]] | None: ``{command, args}`` or ``None`` when disabled/non-host.

    Raises:
        SkillExecutionError: When enabled host target but preconditions are not met.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> mcp_stdio_entry(WorkspaceConfig.minimal()) is None
        True
    """
    if not computer_use_mcp_enabled(workspace):
        return None
    validate_computer_use_host(cfg=workspace)
    return {
        "command": resolve_cua_driver_command(workspace),
        "args": list(CUA_DRIVER_MCP_ARGS),
    }


def merge_computer_use_mcp_server(
    config_doc: dict[str, Any],
    *,
    workspace: WorkspaceConfig,
) -> None:
    """Inject Cua Driver stdio registration into ``config_doc`` (in-place).

    Args:
        config_doc (dict[str, Any]): Effective or preview config document.
        workspace (WorkspaceConfig): Parsed workspace config.

    Returns:
        None

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> doc: dict[str, object] = {}
        >>> merge_computer_use_mcp_server(doc, workspace=WorkspaceConfig.minimal())
        >>> doc.get("mcp_servers") is None
        True
    """
    entry = mcp_stdio_entry(workspace)
    if entry is None:
        return
    servers_raw = config_doc.get("mcp_servers")
    servers: dict[str, Any] = dict(servers_raw) if isinstance(servers_raw, dict) else {}
    servers[CUA_DRIVER_MCP_SERVER_ID] = entry
    config_doc["mcp_servers"] = servers


__all__ = [
    "COMPUTER_USE_SKILL_ID",
    "COMPUTER_USE_TARGETS",
    "COMPUTER_USE_TARGET_HOST",
    "CUA_CLI_BINARY_NAME",
    "CUA_DRIVER_BINARY_NAME",
    "CUA_DRIVER_MCP_ARGS",
    "CUA_DRIVER_MCP_SERVER_ID",
    "SANDBOX_COMPUTER_USE_TARGETS",
    "computer_use_config_enabled",
    "computer_use_mcp_enabled",
    "computer_use_snapshot_annotate_enabled",
    "computer_use_trajectory_export_dir",
    "computer_use_trajectory_share_enabled",
    "computer_use_uses_cua_driver_mcp",
    "gate_computer_use_core_skill",
    "mcp_stdio_entry",
    "merge_computer_use_mcp_server",
    "resolve_computer_use_target",
    "resolve_cua_cli_command",
    "resolve_cua_do_switch_provider",
    "resolve_cua_driver_command",
    "validate_computer_use_host",
]
