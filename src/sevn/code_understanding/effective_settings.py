"""Effective code-understanding settings when a sevn.bot checkout is available.

Module: sevn.code_understanding.effective_settings
Depends: sevn.code_understanding.models, sevn.config.workspace_config

Exports:
    graphify_enabled_for_checkout — whether Graphify should run for this install.
    effective_graphify_settings — merge workspace config with sevn.bot install preset.
    effective_code_understanding — root ``code_understanding`` with install preset applied.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

from sevn.code_understanding.models import CodeUnderstandingSettings, GraphifySettings
from sevn.config.workspace_config import WorkspaceConfig  # noqa: TC001


def graphify_enabled_for_checkout(
    workspace: WorkspaceConfig,
    checkout: Path | None,
) -> bool:
    """Return True when Graphify should be treated as on for this operator install.

    Args:
        workspace (WorkspaceConfig): Parsed workspace root.
        checkout (Path | None): Resolved sevn.bot checkout, if any.

    Returns:
        bool: True when checkout exists and Graphify is explicitly enabled or the
            workspace has a ``my_sevn`` subtree (My Sevn.bot install preset).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> graphify_enabled_for_checkout(WorkspaceConfig.minimal(), None)
        False
    """
    if checkout is None:
        return False
    cu = workspace.code_understanding
    if cu is not None and cu.graphify is not None and cu.graphify.enabled:
        return True
    return workspace.my_sevn is not None


def effective_graphify_settings(
    workspace: WorkspaceConfig,
    checkout: Path | None,
) -> GraphifySettings:
    """Return Graphify settings with install preset applied when appropriate.

    When :func:`graphify_enabled_for_checkout` is true and the workspace block is
    absent or has ``enabled=False``, returns a copy with ``enabled=True`` so
    bootstrap profiles can attach to the checkout.

    Args:
        workspace (WorkspaceConfig): Parsed workspace root.
        checkout (Path | None): Resolved sevn.bot checkout.

    Returns:
        GraphifySettings: Settings to pass to :func:`~sevn.code_understanding.graphify.resolve_profiles`.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> s = effective_graphify_settings(WorkspaceConfig.minimal(), None)
        >>> s.enabled
        False
    """
    cu = workspace.code_understanding
    base = cu.graphify if cu is not None and cu.graphify is not None else GraphifySettings()
    if not graphify_enabled_for_checkout(workspace, checkout):
        return base
    if base.enabled:
        return base
    return base.model_copy(update={"enabled": True})


def effective_code_understanding(
    workspace: WorkspaceConfig,
    checkout: Path | None,
) -> CodeUnderstandingSettings | None:
    """Return code_understanding with effective Graphify preset when checkout resolves.

    Args:
        workspace (WorkspaceConfig): Parsed workspace root.
        checkout (Path | None): Resolved sevn.bot checkout.

    Returns:
        CodeUnderstandingSettings | None: Effective subtree, or workspace value unchanged.

    Examples:
        >>> effective_code_understanding(WorkspaceConfig.minimal(), None) is None
        True
    """
    cu = workspace.code_understanding
    if cu is None:
        if checkout is None or workspace.my_sevn is None:
            return None
        return CodeUnderstandingSettings(graphify=effective_graphify_settings(workspace, checkout))
    gf = effective_graphify_settings(workspace, checkout)
    if cu.graphify == gf:
        return cu
    return cu.model_copy(update={"graphify": gf})


__all__ = [
    "effective_code_understanding",
    "effective_graphify_settings",
    "graphify_enabled_for_checkout",
]
