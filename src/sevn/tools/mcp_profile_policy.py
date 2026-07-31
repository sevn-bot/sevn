"""Per-profile MCP server enablement layered on workspace ``mcp_enabled`` (#90, W29.2).

Module: sevn.tools.mcp_profile_policy
Depends: sevn.config.workspace_config

Exports:
    resolve_mcp_servers_for_profile — filter declared servers by workspace + profile policy.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sevn.config.workspace_config import WorkspaceConfig


def _routing_profiles(workspace: WorkspaceConfig) -> dict[str, Any]:
    """Return the routing profile map from workspace extras.

    Accepts top-level ``routing_profiles`` (W29 tests) and ``routing.profiles`` (W12).

    Args:
        workspace (WorkspaceConfig): Parsed workspace.

    Returns:
        dict[str, Any]: Profile id → profile blob.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _routing_profiles(WorkspaceConfig.minimal())
        {}
    """
    extra = workspace.model_extra or {}
    raw = extra.get("routing_profiles")
    if raw is None:
        raw = getattr(workspace, "routing_profiles", None)
    if isinstance(raw, dict):
        return dict(raw)
    routing = extra.get("routing")
    if routing is None:
        routing = getattr(workspace, "routing", None)
    if isinstance(routing, dict):
        profiles = routing.get("profiles")
        if isinstance(profiles, dict):
            return dict(profiles)
    return {}


def _workspace_mcp_enabled(workspace: WorkspaceConfig) -> list[str]:
    """Read workspace-level ``mcp_enabled`` ids.

    Args:
        workspace (WorkspaceConfig): Parsed workspace.

    Returns:
        list[str]: Enabled server ids (may be empty).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _workspace_mcp_enabled(WorkspaceConfig.minimal())
        []
    """
    extra = workspace.model_extra or {}
    raw = extra.get("mcp_enabled")
    if raw is None:
        raw = getattr(workspace, "mcp_enabled", None)
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def resolve_mcp_servers_for_profile(
    workspace: WorkspaceConfig,
    *,
    profile_id: str | None,
    declared_servers: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Return effective MCP server rows for a routing profile.

    Workspace ``mcp_enabled`` is the baseline allowlist. A profile may further disable
    servers via ``mcp_disabled_servers`` without re-declaring the full server map.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.
        profile_id (str | None): Active routing profile id, or ``None`` for default.
        declared_servers (Mapping[str, Mapping[str, Any]]): Effective ``mcp_servers`` map.

    Returns:
        dict[str, Any]: Filtered server id → ``{command, args, …}`` rows.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> ws = WorkspaceConfig.minimal()
        >>> ws.mcp_enabled = ["a"]
        >>> resolve_mcp_servers_for_profile(
        ...     ws,
        ...     profile_id=None,
        ...     declared_servers={"a": {"command": "echo", "args": []}, "b": {"command": "cat", "args": []}},
        ... )
        {'a': {'command': 'echo', 'args': []}}
    """
    enabled_ids = set(_workspace_mcp_enabled(workspace))
    disabled_ids: set[str] = set()
    if profile_id:
        profile = _routing_profiles(workspace).get(profile_id)
        if isinstance(profile, dict):
            raw_disabled = profile.get("mcp_disabled_servers")
            if isinstance(raw_disabled, list):
                disabled_ids = {str(item).strip() for item in raw_disabled if str(item).strip()}

    effective: dict[str, Any] = {}
    for server_id, spec in declared_servers.items():
        if enabled_ids and server_id not in enabled_ids:
            continue
        if server_id in disabled_ids:
            continue
        if isinstance(spec, dict):
            effective[server_id] = dict(spec)
    return effective


__all__ = ["resolve_mcp_servers_for_profile"]
