"""External system integrations (scaffold).

Module: sevn.integrations
Depends: sevn.integrations.github_skill, sevn.integrations.twexapi

Exports:
    github_skill — GitHub REST helpers for bundled github-manager / gh-pr / gh-issues skills.
    twexapi — TwexAPI client for the social_media_manager specialist.
"""

from __future__ import annotations

from sevn.integrations import github_skill, twexapi

__all__ = ["github_skill", "twexapi"]
