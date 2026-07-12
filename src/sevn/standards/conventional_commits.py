"""Conventional Commits standard loader for agents and tooling.

Module: sevn.standards.conventional_commits
Depends: importlib.resources

Exports:
    conventional_commits_markdown — packaged ``conventional-commits.md`` body.
    conventional_commits_prompt_block — short markdown for tier-B when editing code.
"""

from __future__ import annotations

from importlib import resources
from typing import Final

_PROMPT_MAX_CHARS: Final[int] = 2400


def conventional_commits_markdown() -> str:
    """Return the packaged Conventional Commits standard markdown.

    Returns:
        str: Full text of ``src/sevn/data/standards/conventional-commits.md``.

    Raises:
        FileNotFoundError: When the packaged file is missing from the wheel.

    Examples:
        >>> "Conventional Commits" in conventional_commits_markdown()
        True
    """
    ref = resources.files("sevn.data.standards") / "conventional-commits.md"
    if not ref.is_file():
        msg = "packaged standard not found: conventional-commits.md"
        raise FileNotFoundError(msg)
    return ref.read_text(encoding="utf-8")


def conventional_commits_prompt_block() -> str:
    """Return a bounded markdown block for tier-B commit guidance.

    Returns:
        str: Section header plus standard text, truncated when very long.

    Examples:
        >>> block = conventional_commits_prompt_block()
        >>> block.startswith("## Git commits")
        True
    """
    body = conventional_commits_markdown().strip()
    if len(body) > _PROMPT_MAX_CHARS:
        body = f"{body[: _PROMPT_MAX_CHARS - 3].rstrip()}..."
    return (
        "## Git commits (Conventional Commits 1.0.0)\n"
        "When the operator asks for a commit, or you run `git commit` after editing "
        "any tracked code, use this format. The repo `commit-msg` hook "
        "rejects non-conforming subjects.\n\n"
        f"{body}\n"
    )


__all__ = ["conventional_commits_markdown", "conventional_commits_prompt_block"]
