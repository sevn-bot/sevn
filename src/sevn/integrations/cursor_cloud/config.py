"""Workspace config helpers for ``cursor_cloud`` skill.

Module: sevn.integrations.cursor_cloud.config
Depends: sevn.config.loader, sevn.config.workspace_config

Exports:
    load_cursor_cloud_settings — parse ``skills.cursor_cloud`` block from workspace.
    CursorCloudSettings — resolved defaults for launch scripts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — runtime workspace root resolution
from typing import Any

from sevn.config.loader import find_sevn_json, load_workspace
from sevn.config.workspace_config import WorkspaceConfig  # noqa: TC001


@dataclass(frozen=True)
class CursorCloudSettings:
    """Resolved launch defaults from workspace config.

    Attributes:
        enabled (bool): ``skills.cursor_cloud.enabled``.
        default_repo_url (str | None): Fallback repository URL.
        default_ref (str): Default git ref.
        default_model (str): Model id for create payload.
        auto_create_pr (bool): Default PR creation flag.
        default_mcp_profile (str | None): Named MCP profile when CLI omits flag.
    """

    enabled: bool = False
    default_repo_url: str | None = None
    default_ref: str = "main"
    default_model: str = "composer-2"
    auto_create_pr: bool = True
    default_mcp_profile: str | None = None


def _block_from_config(cfg: WorkspaceConfig | None) -> dict[str, Any]:
    """Return ``skills.cursor_cloud`` mapping.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        dict[str, Any]: Block or empty dict.

    Examples:
        >>> _block_from_config(None)
        {}
    """
    if cfg is None or not isinstance(cfg.skills, dict):
        return {}
    block = cfg.skills.get("cursor_cloud")
    return block if isinstance(block, dict) else {}


def load_cursor_cloud_settings(
    workspace: Path,
) -> tuple[CursorCloudSettings, WorkspaceConfig | None]:
    """Load cursor cloud settings for a workspace content root.

    Args:
        workspace (Path): ``SEVN_WORKSPACE`` content root.

    Returns:
        tuple[CursorCloudSettings, WorkspaceConfig | None]: Settings and parsed config.

    Examples:
        >>> from pathlib import Path
        >>> s, _ = load_cursor_cloud_settings(Path("."))
        >>> isinstance(s, CursorCloudSettings)
        True
    """
    sevn_json = find_sevn_json(workspace)
    if sevn_json is None:
        return CursorCloudSettings(), None
    cfg, _layout = load_workspace(sevn_json=sevn_json)
    block = _block_from_config(cfg)
    repo = block.get("default_repo_url")
    repo_url = str(repo).strip() if isinstance(repo, str) and repo.strip() else None
    ref = block.get("default_ref")
    model = block.get("default_model")
    mcp_prof = block.get("default_mcp_profile")
    return (
        CursorCloudSettings(
            enabled=bool(block.get("enabled", False)),
            default_repo_url=repo_url,
            default_ref=str(ref).strip() if isinstance(ref, str) and ref.strip() else "main",
            default_model=str(model).strip()
            if isinstance(model, str) and model.strip()
            else "composer-2",
            auto_create_pr=bool(block.get("auto_create_pr", True)),
            default_mcp_profile=(
                str(mcp_prof).strip() if isinstance(mcp_prof, str) and mcp_prof.strip() else None
            ),
        ),
        cfg,
    )
