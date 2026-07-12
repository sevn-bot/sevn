"""Pull request operations for bundled ``gh-pr`` skill scripts.

Module: sevn.integrations.github_skill.gh_pr
Depends: sevn.integrations.github_skill.client, sevn.integrations.github_skill.hooks

Exports:
    list_pull_requests — list PRs for a repository.
    view_pull_request — fetch one PR with metadata.
    create_pull_request — open a PR from head to base.
    merge_pull_request — merge an open PR.
    close_pull_request — close a PR without merging.
    update_pull_request_reviewers — add or remove requested reviewers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sevn.integrations.github_skill.client import github_integration_call, parse_github_repo

if TYPE_CHECKING:
    from sevn.integrations.github_skill.hooks import GithubSkillHooks


async def list_pull_requests(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    state: str = "open",
) -> dict[str, Any]:
    """List pull requests for a repository.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.
        state (str, optional): ``open``, ``closed``, or ``all``. Defaults to ``open``.

    Returns:
        dict[str, Any]: Payload with ``pull_requests`` list.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"items": [{"number": 1}]}
        >>> asyncio.run(
        ...     list_pull_requests(GithubSkillHooks(integration_call=_fake), repo="o/r")
        ... )["count"]
        1
    """
    owner, name = parse_github_repo(repo)
    payload = await github_integration_call(
        "pulls.list",
        {"owner": owner, "repo": name, "state": state},
        hooks=hooks,
    )
    pulls = payload.get("items") or payload.get("pull_requests") or []
    if not isinstance(pulls, list):
        pulls = []
    return {
        "owner": owner,
        "repo": name,
        "state": state,
        "pull_requests": pulls,
        "count": len(pulls),
    }


async def view_pull_request(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    pull_number: int,
) -> dict[str, Any]:
    """Fetch one pull request by number.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.
        pull_number (int): PR number.

    Returns:
        dict[str, Any]: PR payload under ``pull_request``.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"number": 7, "title": "Fix"}
        >>> asyncio.run(
        ...     view_pull_request(GithubSkillHooks(integration_call=_fake), repo="o/r", pull_number=7)
        ... )["pull_request"]["number"]
        7
    """
    owner, name = parse_github_repo(repo)
    payload = await github_integration_call(
        "pulls.get",
        {"owner": owner, "repo": name, "pull_number": int(pull_number)},
        hooks=hooks,
    )
    return {
        "owner": owner,
        "repo": name,
        "pull_number": int(pull_number),
        "pull_request": payload,
    }


async def create_pull_request(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str = "main",
    draft: bool = False,
) -> dict[str, Any]:
    """Create a pull request.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug (base repo).
        title (str): PR title.
        body (str): PR body markdown.
        head (str): Head branch or ``owner:branch`` for forks.
        base (str, optional): Base branch. Defaults to ``main``.
        draft (bool, optional): Create as draft. Defaults to ``False``.

    Returns:
        dict[str, Any]: Created PR payload.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"number": 3}
        >>> asyncio.run(
        ...     create_pull_request(
        ...         GithubSkillHooks(integration_call=_fake),
        ...         repo="o/r",
        ...         title="T",
        ...         body="B",
        ...         head="feature",
        ...     )
        ... )["pull_request"]["number"]
        3
    """
    owner, name = parse_github_repo(repo)
    payload = await github_integration_call(
        "pulls.create",
        {
            "owner": owner,
            "repo": name,
            "title": title.strip(),
            "body": body,
            "head": head.strip(),
            "base": base.strip() or "main",
            "draft": bool(draft),
        },
        hooks=hooks,
    )
    return {"owner": owner, "repo": name, "pull_request": payload}


async def merge_pull_request(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    pull_number: int,
    merge_method: str = "squash",
) -> dict[str, Any]:
    """Merge an open pull request.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.
        pull_number (int): PR number.
        merge_method (str, optional): ``merge``, ``squash``, or ``rebase``.

    Returns:
        dict[str, Any]: Merge result payload.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"merged": True}
        >>> asyncio.run(
        ...     merge_pull_request(GithubSkillHooks(integration_call=_fake), repo="o/r", pull_number=1)
        ... )["result"]["merged"]
        True
    """
    owner, name = parse_github_repo(repo)
    payload = await github_integration_call(
        "pulls.merge",
        {
            "owner": owner,
            "repo": name,
            "pull_number": int(pull_number),
            "merge_method": merge_method,
        },
        hooks=hooks,
    )
    return {"owner": owner, "repo": name, "pull_number": int(pull_number), "result": payload}


async def close_pull_request(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    pull_number: int,
) -> dict[str, Any]:
    """Close a pull request without merging.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.
        pull_number (int): PR number.

    Returns:
        dict[str, Any]: Updated PR payload.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"state": "closed"}
        >>> asyncio.run(
        ...     close_pull_request(GithubSkillHooks(integration_call=_fake), repo="o/r", pull_number=2)
        ... )["pull_request"]["state"]
        'closed'
    """
    owner, name = parse_github_repo(repo)
    payload = await github_integration_call(
        "pulls.update",
        {
            "owner": owner,
            "repo": name,
            "pull_number": int(pull_number),
            "state": "closed",
        },
        hooks=hooks,
    )
    return {"owner": owner, "repo": name, "pull_number": int(pull_number), "pull_request": payload}


async def update_pull_request_reviewers(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    pull_number: int,
    reviewers_add: list[str] | None = None,
    reviewers_remove: list[str] | None = None,
) -> dict[str, Any]:
    """Add or remove requested reviewers on a pull request.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.
        pull_number (int): PR number.
        reviewers_add (list[str] | None, optional): Usernames to request review from.
        reviewers_remove (list[str] | None, optional): Usernames to remove from review.

    Returns:
        dict[str, Any]: Reviewer update payload.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"requested_reviewers": ["alice"]}
        >>> asyncio.run(
        ...     update_pull_request_reviewers(
        ...         GithubSkillHooks(integration_call=_fake),
        ...         repo="o/r",
        ...         pull_number=4,
        ...         reviewers_add=["alice"],
        ...     )
        ... )["result"]["requested_reviewers"][0]
        'alice'
    """
    owner, name = parse_github_repo(repo)
    body: dict[str, Any] = {
        "owner": owner,
        "repo": name,
        "pull_number": int(pull_number),
    }
    if reviewers_add:
        body["reviewers"] = list(reviewers_add)
    if reviewers_remove:
        body["reviewers_remove"] = list(reviewers_remove)
    payload = await github_integration_call("pulls.request_reviewers", body, hooks=hooks)
    return {"owner": owner, "repo": name, "pull_number": int(pull_number), "result": payload}
