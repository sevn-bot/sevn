"""Issue operations for bundled ``gh-issues`` skill scripts.

Module: sevn.integrations.github_skill.gh_issues
Depends: sevn.integrations.github_skill.client, sevn.integrations.github_skill.hooks

Exports:
    list_issues — list repository issues.
    view_issue — fetch one issue by number.
    create_issue — open a new issue.
    comment_on_issue — add an issue comment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sevn.integrations.github_skill.client import (
    github_integration_call,
    github_legacy_call,
    parse_github_repo,
)

if TYPE_CHECKING:
    from sevn.integrations.github_skill.hooks import GithubSkillHooks


async def list_issues(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    state: str = "open",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """List issues for a repository via legacy ``gh_repo_list_issues`` mapping.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.
        state (str, optional): ``open``, ``closed``, or ``all``. Defaults to ``open``.
        labels (list[str] | None, optional): Optional label filter list.

    Returns:
        dict[str, Any]: Payload with ``issues`` list.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"items": [{"number": 2}]}
        >>> asyncio.run(list_issues(GithubSkillHooks(integration_call=_fake), repo="o/r"))["count"]
        1
    """
    owner, name = parse_github_repo(repo)
    args: dict[str, Any] = {"owner": owner, "repo": name, "state": state}
    if labels:
        args["labels"] = ",".join(labels)
    payload = await github_legacy_call("gh_repo_list_issues", args, hooks=hooks)
    issues = payload.get("items") or payload.get("issues") or []
    if not isinstance(issues, list):
        issues = []
    return {"owner": owner, "repo": name, "state": state, "issues": issues, "count": len(issues)}


async def view_issue(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    issue_number: int,
) -> dict[str, Any]:
    """Fetch one issue by number.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.
        issue_number (int): Issue number.

    Returns:
        dict[str, Any]: Issue payload under ``issue``.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"number": 5, "title": "Bug"}
        >>> asyncio.run(
        ...     view_issue(GithubSkillHooks(integration_call=_fake), repo="o/r", issue_number=5)
        ... )["issue"]["title"]
        'Bug'
    """
    owner, name = parse_github_repo(repo)
    payload = await github_integration_call(
        "issues.get",
        {"owner": owner, "repo": name, "issue_number": int(issue_number)},
        hooks=hooks,
    )
    return {"owner": owner, "repo": name, "issue_number": int(issue_number), "issue": payload}


async def create_issue(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    title: str,
    body: str = "",
    labels: list[str] | None = None,
    assignees: list[str] | None = None,
) -> dict[str, Any]:
    """Create a repository issue via legacy ``gh_repo_create_issue`` mapping.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.
        title (str): Issue title.
        body (str, optional): Issue body markdown. Defaults to empty string.
        labels (list[str] | None, optional): Label names to apply.
        assignees (list[str] | None, optional): Assignee usernames.

    Returns:
        dict[str, Any]: Created issue payload.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"number": 9}
        >>> asyncio.run(
        ...     create_issue(
        ...         GithubSkillHooks(integration_call=_fake),
        ...         repo="o/r",
        ...         title="T",
        ...     )
        ... )["issue"]["number"]
        9
    """
    owner, name = parse_github_repo(repo)
    args: dict[str, Any] = {"owner": owner, "repo": name, "title": title.strip(), "body": body}
    if labels:
        args["labels"] = list(labels)
    if assignees:
        args["assignees"] = list(assignees)
    payload = await github_legacy_call("gh_repo_create_issue", args, hooks=hooks)
    return {"owner": owner, "repo": name, "issue": payload}


async def comment_on_issue(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    issue_number: int,
    body: str,
) -> dict[str, Any]:
    """Add a comment to an issue.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.
        issue_number (int): Issue number.
        body (str): Comment markdown body.

    Returns:
        dict[str, Any]: Created comment payload.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"id": 100}
        >>> asyncio.run(
        ...     comment_on_issue(
        ...         GithubSkillHooks(integration_call=_fake),
        ...         repo="o/r",
        ...         issue_number=1,
        ...         body="Thanks",
        ...     )
        ... )["comment"]["id"]
        100
    """
    owner, name = parse_github_repo(repo)
    payload = await github_integration_call(
        "issues.create_comment",
        {
            "owner": owner,
            "repo": name,
            "issue_number": int(issue_number),
            "body": body,
        },
        hooks=hooks,
    )
    return {
        "owner": owner,
        "repo": name,
        "issue_number": int(issue_number),
        "comment": payload,
    }
