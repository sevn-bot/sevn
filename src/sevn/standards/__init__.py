"""Packaged engineering standards loaded at runtime.

Module: sevn.standards
Depends: sevn.standards.conventional_commits

Exports:
    conventional_commits_markdown — full Conventional Commits guide text.
    conventional_commits_prompt_block — trimmed block for tier-B system prompts.
"""

from sevn.standards.conventional_commits import (
    conventional_commits_markdown,
    conventional_commits_prompt_block,
)

__all__ = [
    "conventional_commits_markdown",
    "conventional_commits_prompt_block",
]
