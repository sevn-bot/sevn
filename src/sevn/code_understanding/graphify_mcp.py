"""Graphify + code-understanding MCP gateway registration (`specs/28-code-understanding.md` §4.4).

Exports:
    graphify_mcp_enabled — whether explicit Graphify MCP opt-in is on.
    graphify_mcp_server_ids — MCP server ids to register (default profile only).
    merge_gateway_mcp_servers — inject synthetic stdio rows into a config document.
    build_effective_mcp_servers — merged ``mcp_servers`` map for gateway bootstrap.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sevn.code_understanding.graphify import resolve_profiles
from sevn.code_understanding.models import GraphifySettings  # noqa: TC001
from sevn.config.workspace_config import WorkspaceConfig  # noqa: TC001


def graphify_mcp_enabled(workspace: WorkspaceConfig) -> bool:
    """Return True when ``code_understanding.graphify.mcp.enabled`` is set.

    Args:
        workspace (WorkspaceConfig): Parsed workspace.

    Returns:
        bool: Explicit MCP opt-in flag.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> graphify_mcp_enabled(WorkspaceConfig.minimal()) is False
        True
    """
    cu = workspace.code_understanding
    if cu is None or cu.graphify is None:
        return False
    mcp = cu.graphify.mcp
    if not isinstance(mcp, dict):
        return False
    return bool(mcp.get("enabled"))


def graphify_mcp_server_ids(
    settings: GraphifySettings,
    *,
    primary_repo_root: str = ".",
) -> list[str]:
    """List MCP server ids for the default-profile-only topology.

    Args:
        settings (GraphifySettings): Graphify config subtree.
        primary_repo_root (str, optional): Repo root for bootstrap. Defaults to ``"."``.

    Returns:
        list[str]: Profile ids when MCP enabled and profiles resolve.

    Examples:
        >>> graphify_mcp_server_ids(GraphifySettings(enabled=False))
        []
    """
    from pathlib import Path

    profiles = resolve_profiles(settings, Path(primary_repo_root))
    return [p.id for p in profiles]


def _declared_mcp_servers(workspace: WorkspaceConfig) -> dict[str, Any]:
    """Return operator-declared ``mcp_servers`` from workspace extras.

    Args:
        workspace (WorkspaceConfig): Parsed workspace.

    Returns:
        dict[str, Any]: Copy of declared servers (may be empty).

    Examples:
        >>> _declared_mcp_servers(WorkspaceConfig.minimal())
        {}
    """
    extra = workspace.model_extra or {}
    raw = extra.get("mcp_servers")
    if raw is None:
        raw = getattr(workspace, "mcp_servers", None)
    return dict(raw) if isinstance(raw, dict) else {}


def merge_gateway_mcp_servers(
    config_doc: dict[str, Any],
    *,
    workspace: WorkspaceConfig,
    content_root: Path,
) -> None:
    """Merge synthetic stdio MCP entries from code-understanding toggles (host gateway).

    Args:
        config_doc (dict[str, Any]): Effective or preview config document (mutated).
        workspace (WorkspaceConfig): Parsed workspace.
        content_root (Path): Workspace content root for path policy.

    Returns:
        None

    Examples:
        >>> from pathlib import Path as _P
        >>> doc: dict[str, object] = {"mcp_servers": {"x": {"command": "echo", "args": []}}}
        >>> merge_gateway_mcp_servers(
        ...     doc, workspace=WorkspaceConfig.minimal(), content_root=_P("/w")
        ... )
        >>> doc["mcp_servers"]["x"]["command"]
        'echo'
    """
    from sevn.code_understanding.code_review_graph_mcp import (
        merge_code_review_graph_mcp_server,
    )
    from sevn.skills.computer_use import merge_computer_use_mcp_server

    merge_code_review_graph_mcp_server(
        config_doc,
        workspace=workspace,
        content_root=content_root,
    )
    merge_computer_use_mcp_server(config_doc, workspace=workspace)


def build_effective_mcp_servers(
    workspace: WorkspaceConfig,
    content_root: Path,
) -> dict[str, Any]:
    """Return merged ``mcp_servers`` for gateway MCP stdio registration.

    Operator-declared rows are preserved; code-understanding synthetic rows are
    layered on top when ``enabled`` + explicit ``mcp`` opt-in gates pass.

    Args:
        workspace (WorkspaceConfig): Parsed workspace.
        content_root (Path): Workspace content root.

    Returns:
        dict[str, Any]: Server id → ``{command, args}`` mapping.

    Examples:
        >>> from pathlib import Path as _P
        >>> build_effective_mcp_servers(WorkspaceConfig.minimal(), _P("/w"))
        {}
    """
    doc: dict[str, Any] = {"mcp_servers": _declared_mcp_servers(workspace)}
    merge_gateway_mcp_servers(doc, workspace=workspace, content_root=content_root)
    merged = doc.get("mcp_servers")
    return dict(merged) if isinstance(merged, dict) else {}


__all__ = [
    "build_effective_mcp_servers",
    "graphify_mcp_enabled",
    "graphify_mcp_server_ids",
    "merge_gateway_mcp_servers",
]
