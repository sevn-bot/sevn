"""GitHub bundled skill helpers — REST via ``integration_call`` proxy.

Module: sevn.integrations.github_skill
Depends: sevn.integrations.github_skill.client, sevn.integrations.github_skill.gh_issues,
    sevn.integrations.github_skill.gh_pr, sevn.integrations.github_skill.github_manager,
    sevn.integrations.github_skill.hooks

Exports:
    GithubSkillHooks — injectable integration delegate.
    resolve_github_skill_hooks — resolve hooks from env or overrides.
    integration_call_from_mapping — test double integration client.
    parse_github_repo — parse owner/repo slug.
    github_integration_call — async GitHub REST dispatch.
    github_integration_call_sync — sync wrapper.
    github_legacy_call — legacy ``gh_repo_*`` alias dispatch.
    github_manager — branch/Actions/secrets/deploy operations module.
    gh_pr — pull request operations module.
    gh_issues — issue operations module.
"""

from __future__ import annotations

from sevn.integrations.github_skill import gh_issues as gh_issues
from sevn.integrations.github_skill import gh_pr as gh_pr
from sevn.integrations.github_skill import github_manager as github_manager
from sevn.integrations.github_skill.client import (
    github_integration_call,
    github_integration_call_sync,
    github_legacy_call,
    parse_github_repo,
)
from sevn.integrations.github_skill.hooks import (
    GithubSkillHooks,
    integration_call_from_mapping,
    resolve_github_skill_hooks,
)

__all__ = [
    "GithubSkillHooks",
    "gh_issues",
    "gh_pr",
    "github_integration_call",
    "github_integration_call_sync",
    "github_legacy_call",
    "github_manager",
    "integration_call_from_mapping",
    "parse_github_repo",
    "resolve_github_skill_hooks",
]
