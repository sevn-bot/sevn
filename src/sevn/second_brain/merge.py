"""Optional git merge conflict path (`specs/27-second-brain.md` §4, PRD §5.8).

Exports:
    SecondBrainMergeToolError — merge path unavailable in this build.
    try_git_merge — attempt git-backed merge when strategy allows (stub).
"""

from __future__ import annotations

from sevn.config.workspace_config import SecondBrainWorkspaceConfig
from sevn.second_brain.errors import SecondBrainError


class SecondBrainMergeToolError(SecondBrainError):
    """Three-way merge unavailable or misconfigured."""


def try_git_merge(
    *,
    workspace_root: object,
    wiki_file: object,
    theirs_patch: str,
    cfg: SecondBrainWorkspaceConfig | None,
) -> str:
    """Attempt git-backed merge when strategy allows and GitHub integration exists.

    Args:
        workspace_root (object): Workspace root (reserved for future Git wiring).
        wiki_file (object): Target wiki file (reserved for future Git wiring).
        theirs_patch (str): Patch text from remote (reserved for future Git wiring).
        cfg (SecondBrainWorkspaceConfig | None): Workspace second-brain config slice.

    Returns:
        str: Merged text when implemented (not reached in this build).

    Raises:
        SecondBrainMergeToolError: Always in this build — wire-up deferred (`specs/27` §11).

    Examples:
        >>> try_git_merge.__name__
        'try_git_merge'
    """

    _ = workspace_root
    _ = wiki_file
    _ = theirs_patch
    if cfg is None or cfg.conflict_strategy != "git_merge":
        msg = "git_merge not selected (second_brain.conflict_strategy)"
        raise SecondBrainMergeToolError(msg)
    msg = (
        "second_brain git_merge requires GitHub integration — not configured in this workspace "
        "(use atomic_reject / resolve in Obsidian; `specs/27-second-brain.md` §11)"
    )
    raise SecondBrainMergeToolError(msg)


__all__ = ["SecondBrainMergeToolError", "try_git_merge"]
