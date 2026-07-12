"""External system integrations (scaffold).

Module: sevn.integrations
Depends: sevn.integrations.github_skill

Exports:
    github_skill — GitHub REST helpers for bundled github-manager / gh-pr / gh-issues skills.
"""

from __future__ import annotations

from sevn.integrations import github_skill

__all__ = ["github_skill"]
