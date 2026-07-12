"""Workspace-derived trigger tunables (`specs/30-non-interactive-triggers.md` §5).

Module: sevn.triggers.settings
Depends: sevn.config

Exports:
    effective_max_concurrent — semaphore limit.
    effective_max_inline_bytes — spill threshold bytes.

Examples:
    >>> from sevn.config.workspace_config import WorkspaceConfig
    >>> from sevn.triggers.settings import effective_max_concurrent
    >>> effective_max_concurrent(WorkspaceConfig.minimal()) >= 1
    True
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sevn.config.defaults import DEFAULT_TRIGGERS_MAX_CONCURRENT, DEFAULT_TRIGGERS_MAX_INLINE_BYTES

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig


def effective_max_concurrent(ws: WorkspaceConfig) -> int:
    """Return ``triggers.max_concurrent`` or legacy ``max_parallel_runs`` or default.

    Args:
        ws (WorkspaceConfig): Workspace document.

    Returns:
        int: Positive concurrency ceiling.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig, TriggersWorkspaceConfig
        >>> ws = WorkspaceConfig.minimal(triggers=TriggersWorkspaceConfig(max_concurrent=3))
        >>> effective_max_concurrent(ws)
        3
    """
    t = ws.triggers
    if t is None:
        return int(DEFAULT_TRIGGERS_MAX_CONCURRENT)
    return int(t.max_concurrent)


def effective_max_inline_bytes(ws: WorkspaceConfig) -> int:
    """Return configured inline prompt cap or default.

    Args:
        ws (WorkspaceConfig): Workspace document.

    Returns:
        int: Byte cap for inlined ``prompt`` before inbox spill.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig, TriggersWorkspaceConfig
        >>> ws = WorkspaceConfig.minimal(
        ...     triggers=TriggersWorkspaceConfig(max_inline_bytes=2048),
        ... )
        >>> effective_max_inline_bytes(ws)
        2048
    """
    t = ws.triggers
    if t is None:
        return int(DEFAULT_TRIGGERS_MAX_INLINE_BYTES)
    return int(t.max_inline_bytes)
