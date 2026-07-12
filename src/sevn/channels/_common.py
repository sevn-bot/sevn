"""Shared helpers for channel adapters.

Module: sevn.channels._common
Depends: pydantic, sevn.config.workspace_config

Exports:
    PlatformChannelConfig — common ``channels.<name>`` fields.
    platform_config_from_workspace — resolve one channel blob.
    channel_blob — raw dict for adapter-specific keys.
    busy_input_mode_for_channel — read busy mode with default interrupt.
    session_reset_policy_for_channel — read reset policy override.
    dm_policy_for_channel — read DM policy string.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from sevn.config.sections.channels import channel_extra_dict
from sevn.config.workspace_config import WorkspaceConfig

BusyInputMode = Literal["interrupt", "queue", "steer"]
SessionResetPolicy = Literal["daily", "idle", "both", "none"]


class PlatformChannelConfig(BaseModel):
    """Common channel keys shared by plugin adapters."""

    model_config = ConfigDict(extra="allow")

    enabled: bool | None = None
    dm_policy: str | None = None
    allowed_users: list[str] | None = None
    busy_input_mode: BusyInputMode | None = None
    session_reset_policy: SessionResetPolicy | None = None
    webhook_secret_ref: str | None = None
    bot_token_ref: str | None = None


def platform_config_from_workspace(
    workspace: WorkspaceConfig,
    channel_name: str,
) -> PlatformChannelConfig:
    """Materialize one channel config blob from ``channels.<name>``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.
        channel_name (str): Adapter entry-point name.

    Returns:
        PlatformChannelConfig: Defaults when subtree missing.

    Examples:
        >>> platform_config_from_workspace(WorkspaceConfig.minimal(), "discord").enabled
        >>> platform_config_from_workspace(WorkspaceConfig.minimal(), "discord").enabled is None
        True
    """
    ch = workspace.channels
    if ch is None:
        return PlatformChannelConfig()
    blob = channel_extra_dict(ch, channel_name)
    if blob:
        return PlatformChannelConfig.model_validate(blob)
    typed = getattr(ch, channel_name, None)
    if typed is not None and hasattr(typed, "model_dump"):
        return PlatformChannelConfig.model_validate(typed.model_dump(mode="python"))
    return PlatformChannelConfig()


def busy_input_mode_for_channel(workspace: WorkspaceConfig, channel_name: str) -> BusyInputMode:
    """Return configured busy input mode with gateway default fallback.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.
        channel_name (str): Adapter name.

    Returns:
        BusyInputMode: Effective busy mode.

    Examples:
        >>> busy_input_mode_for_channel(WorkspaceConfig.minimal(), "slack")
        'interrupt'
    """
    cfg = platform_config_from_workspace(workspace, channel_name)
    mode = (cfg.busy_input_mode or "interrupt").strip().lower()
    if mode in ("interrupt", "queue", "steer"):
        return mode  # type: ignore[return-value]
    return "interrupt"


def session_reset_policy_for_channel(
    workspace: WorkspaceConfig,
    channel_name: str,
) -> SessionResetPolicy:
    """Return session reset policy override for one adapter.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.
        channel_name (str): Adapter name.

    Returns:
        SessionResetPolicy: Policy string (``none`` when unset).

    Examples:
        >>> session_reset_policy_for_channel(WorkspaceConfig.minimal(), "discord")
        'none'
    """
    cfg = platform_config_from_workspace(workspace, channel_name)
    raw = (cfg.session_reset_policy or "none").strip().lower()
    if raw in ("daily", "idle", "both", "none"):
        return raw  # type: ignore[return-value]
    return "none"


def dm_policy_for_channel(workspace: WorkspaceConfig, channel_name: str) -> str:
    """Return DM policy for one adapter.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.
        channel_name (str): Adapter name.

    Returns:
        str: Policy string defaulting to ``open``.

    Examples:
        >>> dm_policy_for_channel(WorkspaceConfig.minimal(), "discord")
        'open'
    """
    cfg = platform_config_from_workspace(workspace, channel_name)
    return (cfg.dm_policy or "open").strip().lower()


def channel_blob(workspace: WorkspaceConfig, channel_name: str) -> dict[str, Any]:
    """Return raw ``channels.<name>`` dict for adapter-specific keys.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.
        channel_name (str): Adapter name.

    Returns:
        dict[str, Any]: Empty dict when missing.

    Examples:
        >>> channel_blob(WorkspaceConfig.minimal(), "slack")
        {}
    """
    ch = workspace.channels
    if ch is None:
        return {}
    return channel_extra_dict(ch, channel_name)
