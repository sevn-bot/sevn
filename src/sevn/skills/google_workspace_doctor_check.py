"""Google Workspace skill doctor warnings when ``skills.google_workspace.enabled`` is true.

Module: sevn.skills.google_workspace_doctor_check
Depends: pathlib, sevn.config.workspace_config, sevn.skills.google_workspace

Exports:
    probe_google_workspace_skill_warnings — warning strings for Google Workspace readiness.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from sevn.config.workspace_config import WorkspaceConfig, google_workspace_settings
from sevn.skills.google_workspace import REQUIRED_PACKAGES, ensure_google_deps, gws_binary, token_path


def probe_google_workspace_skill_warnings(
    cfg: WorkspaceConfig | None,
    *,
    content_root: Path,
) -> list[str]:
    """Return doctor warning strings for the Google Workspace skill.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config.
        content_root (Path): Workspace content root.

    Returns:
        list[str]: Empty when the skill is disabled or when all checks pass.

    Examples:
        >>> cfg = WorkspaceConfig(
        ...     schema_version=1,
        ...     gateway={"token": "t"},
        ...     skills={"google_workspace": {"enabled": False}},
        ... )
        >>> probe_google_workspace_skill_warnings(cfg, content_root=Path("."))
        []
    """

    settings = google_workspace_settings(cfg)
    if not settings.enabled:
        return []

    warnings: list[str] = []
    stored_token = token_path(content_root)
    if not stored_token.is_file():
        warnings.append(f"google-workspace skill enabled but token missing at {stored_token}")
    if settings.prefer_gws and gws_binary() is None:
        warnings.append("google-workspace prefer_gws=true but gws is not on PATH")
    try:
        ensure_google_deps()
    except ImportError:
        packages = ", ".join(REQUIRED_PACKAGES)
        hint = "uv pip install --python $(which python3) 'sevn[google-workspace]'"
        warnings.append(
            f"google-workspace optional deps not installed ({packages}); run: {hint}",
        )
        logger.debug("google_workspace doctor: optional deps missing ({})", packages)
    return warnings


__all__ = ["probe_google_workspace_skill_warnings"]
