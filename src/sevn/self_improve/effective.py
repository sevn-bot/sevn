"""Resolve effective self-improve enablement (`specs/33-self-improvement.md` §5).

Module: sevn.self_improve.effective
Depends: os, sevn.config.workspace_config

Exports:
    effective_self_improve_enabled — config + ``SEVN_DISABLE_SELF_IMPROVE`` merge.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig


def effective_self_improve_enabled(ws: WorkspaceConfig) -> bool:
    """Return whether the subsystem is permitted to run for this workspace.

    ``SEVN_DISABLE_SELF_IMPROVE=1`` forces false regardless of ``sevn.json``.

        Args:
        ws (WorkspaceConfig): Parsed workspace config.

        Returns:
            bool: Effective enable bit for workers and CLIs.

        Examples:
            >>> from sevn.config.workspace_config import WorkspaceConfig
            >>> effective_self_improve_enabled(WorkspaceConfig.minimal())
            False
    """
    if os.environ.get("SEVN_DISABLE_SELF_IMPROVE", "").strip() == "1":
        return False
    block = ws.self_improve
    return bool(block and block.enabled)
