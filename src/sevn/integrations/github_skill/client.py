"""Shared GitHub skill helpers — repo parsing and integration dispatch.

Module: sevn.integrations.github_skill.client
Depends: asyncio, sevn.config.my_sevn, sevn.integrations.github_skill.hooks,
    sevn.tools.integration_gh_repo

Exports:
    parse_github_repo — split ``owner/repo`` or GitHub URL (wraps config SSOT).
    github_integration_call — dispatch one GitHub REST integration method.
    github_integration_call_sync — synchronous wrapper for integration dispatch.
    github_legacy_call — map historic ``gh_repo_*`` aliases via legacy kwargs helper.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sevn.config.my_sevn import parse_github_repo_slug
from sevn.integrations.github_skill.hooks import GithubSkillHooks, resolve_github_skill_hooks
from sevn.tools.integration_gh_repo import legacy_gh_repo_integration_kwargs


def parse_github_repo(repo: str) -> tuple[str, str]:
    """Parse ``owner`` and ``repo`` from ``owner/repo``, HTTPS, or SCP URL.

    Thin wrapper over :func:`sevn.config.my_sevn.parse_github_repo_slug` so
    config and integrations share one parser.

    Args:
        repo (str): Repository slug, ``https://github.com/…`` URL, or
            ``git@host:owner/repo.git`` SCP form.

    Returns:
        tuple[str, str]: ``(owner, repo_name)``.

    Raises:
        ValueError: When the slug cannot be parsed.

    Examples:
        >>> parse_github_repo("octocat/Hello-World")
        ('octocat', 'Hello-World')
        >>> parse_github_repo("https://github.com/acme/widgets.git")
        ('acme', 'widgets')
        >>> parse_github_repo("git@github.com:acme/app.git")
        ('acme', 'app')
    """
    return parse_github_repo_slug(repo)


async def github_integration_call(
    method: str,
    args: dict[str, Any],
    *,
    hooks: GithubSkillHooks | None = None,
) -> dict[str, Any]:
    """Call one GitHub REST integration method via injectable hooks.

    Args:
        method (str): REST-shaped method (``pulls.list``, ``issues.create``, ...).
        args (dict[str, Any]): Integration ``args`` payload.
        hooks (GithubSkillHooks | None, optional): Hook bundle; defaults to env proxy.

    Returns:
        dict[str, Any]: Integration response payload.

    Raises:
        RuntimeError: When no integration hook is configured or proxy fails.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"number": 1}
        >>> asyncio.run(
        ...     github_integration_call(
        ...         "pulls.get",
        ...         {"owner": "o", "repo": "r", "pull_number": 1},
        ...         hooks=GithubSkillHooks(integration_call=_fake),
        ...     )
        ... )["number"]
        1
    """
    resolved = hooks if hooks is not None else resolve_github_skill_hooks()
    if resolved.integration_call is None:
        msg = "github skill integration hook not configured"
        raise RuntimeError(msg)
    payload = await resolved.integration_call(method, dict(args))
    return payload if isinstance(payload, dict) else {"result": payload}


def github_integration_call_sync(
    method: str,
    args: dict[str, Any],
    *,
    hooks: GithubSkillHooks | None = None,
) -> dict[str, Any]:
    """Synchronous wrapper for :func:`github_integration_call`.

    Args:
        method (str): REST-shaped integration method.
        args (dict[str, Any]): Integration args payload.
        hooks (GithubSkillHooks | None, optional): Hook bundle for tests.

    Returns:
        dict[str, Any]: Integration response payload.

    Examples:
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"ok": True}
        >>> github_integration_call_sync(
        ...     "repos.get",
        ...     {"owner": "o", "repo": "r"},
        ...     hooks=GithubSkillHooks(integration_call=_fake),
        ... )["ok"]
        True
    """
    return asyncio.run(github_integration_call(method, args, hooks=hooks))


async def github_legacy_call(
    legacy_tool_name: str,
    args: dict[str, Any],
    *,
    hooks: GithubSkillHooks | None = None,
) -> dict[str, Any]:
    """Dispatch via :func:`legacy_gh_repo_integration_kwargs` mapping table.

    Args:
        legacy_tool_name (str): Historic ``gh_repo_*`` alias.
        args (dict[str, Any]): Forwarded integration args.
        hooks (GithubSkillHooks | None, optional): Hook bundle for tests.

    Returns:
        dict[str, Any]: Integration response payload.

    Raises:
        ValueError: When ``legacy_tool_name`` is unknown.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"method": _m}
        >>> asyncio.run(
        ...     github_legacy_call(
        ...         "gh_repo_get",
        ...         {"owner": "a", "repo": "b"},
        ...         hooks=GithubSkillHooks(integration_call=_fake),
        ...     )
        ... )["method"]
        'repos.get'
    """
    mapped = legacy_gh_repo_integration_kwargs(legacy_tool_name, args=args)
    if mapped is None:
        msg = f"unknown legacy gh_repo alias: {legacy_tool_name}"
        raise ValueError(msg)
    return await github_integration_call(str(mapped["method"]), dict(mapped["args"]), hooks=hooks)
