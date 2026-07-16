"""GitHub manager operations for bundled ``github-manager`` / ``gh-issues`` skill scripts.

Module: sevn.integrations.github_skill.github_manager
Depends: sevn.integrations.github_skill.client, sevn.integrations.github_skill.hooks

REST manager only — ``gh`` CLI helpers live in
:mod:`sevn.integrations.github_skill.gh_cli`.

Exports:
    list_branches — list repository branches.
    create_branch — create a branch ref.
    delete_branch — delete a branch ref.
    list_workflows — list GitHub Actions workflows.
    dispatch_workflow — trigger or re-run a workflow.
    workflow_run_logs — fetch workflow run + jobs summary.
    list_repo_secrets — list Actions secrets (names only).
    upsert_repo_secret — create or update a repository secret.
    list_repo_variables — list Actions variables.
    upsert_repo_variable — create or update a repository variable.
    list_environments — list deployment environments.
    upsert_environment — create or update an environment.
    create_deployment — trigger a deployment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sevn.integrations.github_skill.client import github_integration_call, parse_github_repo

if TYPE_CHECKING:
    from sevn.integrations.github_skill.hooks import GithubSkillHooks

__all__ = [
    "create_branch",
    "create_deployment",
    "delete_branch",
    "dispatch_workflow",
    "list_branches",
    "list_environments",
    "list_repo_secrets",
    "list_repo_variables",
    "list_workflows",
    "upsert_environment",
    "upsert_repo_secret",
    "upsert_repo_variable",
    "workflow_run_logs",
]


async def list_branches(
    hooks: GithubSkillHooks,
    *,
    repo: str,
) -> dict[str, Any]:
    """List branches for a repository.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.

    Returns:
        dict[str, Any]: Normalised payload with ``branches`` list.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"branches": [{"name": "main"}]}
        >>> out = asyncio.run(list_branches(hooks=GithubSkillHooks(integration_call=_fake), repo="o/r"))
        >>> out["branches"][0]["name"]
        'main'
    """
    owner, name = parse_github_repo(repo)
    payload = await github_integration_call(
        "repos.list_branches",
        {"owner": owner, "repo": name},
        hooks=hooks,
    )
    branches = payload.get("branches") or payload.get("items") or payload
    if not isinstance(branches, list):
        branches = [branches] if branches else []
    return {"owner": owner, "repo": name, "branches": branches, "count": len(branches)}


async def create_branch(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    branch: str,
    from_ref: str,
) -> dict[str, Any]:
    """Create a branch pointing at ``from_ref``.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.
        branch (str): New branch name.
        from_ref (str): Source git ref (branch, tag, or SHA).

    Returns:
        dict[str, Any]: Created ref payload.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"ref": "refs/heads/feature"}
        >>> asyncio.run(
        ...     create_branch(
        ...         GithubSkillHooks(integration_call=_fake),
        ...         repo="o/r",
        ...         branch="feature",
        ...         from_ref="main",
        ...     )
        ... )["result"]["ref"]
        'refs/heads/feature'
    """
    owner, name = parse_github_repo(repo)
    ref_name = branch.strip()
    if not ref_name.startswith("refs/"):
        ref_name = f"refs/heads/{ref_name}"
    payload = await github_integration_call(
        "git.create_ref",
        {"owner": owner, "repo": name, "ref": ref_name, "sha": from_ref.strip()},
        hooks=hooks,
    )
    return {"owner": owner, "repo": name, "branch": branch, "result": payload}


async def delete_branch(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    branch: str,
) -> dict[str, Any]:
    """Delete a branch ref.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.
        branch (str): Branch name to delete.

    Returns:
        dict[str, Any]: Deletion acknowledgement payload.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"deleted": True}
        >>> asyncio.run(
        ...     delete_branch(GithubSkillHooks(integration_call=_fake), repo="o/r", branch="old")
        ... )["result"]["deleted"]
        True
    """
    owner, name = parse_github_repo(repo)
    ref_name = branch.strip()
    if not ref_name.startswith("refs/"):
        ref_name = f"refs/heads/{ref_name}"
    payload = await github_integration_call(
        "git.delete_ref",
        {"owner": owner, "repo": name, "ref": ref_name},
        hooks=hooks,
    )
    return {"owner": owner, "repo": name, "branch": branch, "result": payload}


async def list_workflows(
    hooks: GithubSkillHooks,
    *,
    repo: str,
) -> dict[str, Any]:
    """List GitHub Actions workflows for a repository.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.

    Returns:
        dict[str, Any]: Payload with ``workflows`` list.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"workflows": [{"id": 1, "name": "CI"}]}
        >>> asyncio.run(list_workflows(GithubSkillHooks(integration_call=_fake), repo="o/r"))["count"]
        1
    """
    owner, name = parse_github_repo(repo)
    payload = await github_integration_call(
        "actions.list_repo_workflows",
        {"owner": owner, "repo": name},
        hooks=hooks,
    )
    workflows = payload.get("workflows") or payload.get("items") or []
    if not isinstance(workflows, list):
        workflows = []
    return {"owner": owner, "repo": name, "workflows": workflows, "count": len(workflows)}


async def dispatch_workflow(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    workflow_id: str,
    ref: str,
    inputs: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Trigger a workflow dispatch event.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.
        workflow_id (str): Workflow file name or numeric id.
        ref (str): Git ref to run against.
        inputs (dict[str, str] | None, optional): Workflow dispatch inputs.

    Returns:
        dict[str, Any]: Dispatch acknowledgement payload.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"dispatched": True}
        >>> asyncio.run(
        ...     dispatch_workflow(
        ...         GithubSkillHooks(integration_call=_fake),
        ...         repo="o/r",
        ...         workflow_id="ci.yml",
        ...         ref="main",
        ...     )
        ... )["result"]["dispatched"]
        True
    """
    owner, name = parse_github_repo(repo)
    body: dict[str, Any] = {"owner": owner, "repo": name, "workflow_id": workflow_id, "ref": ref}
    if inputs:
        body["inputs"] = dict(inputs)
    payload = await github_integration_call("actions.create_workflow_dispatch", body, hooks=hooks)
    return {"owner": owner, "repo": name, "workflow_id": workflow_id, "ref": ref, "result": payload}


async def workflow_run_logs(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    run_id: int,
) -> dict[str, Any]:
    """Fetch workflow run metadata and job list (log download via proxy integration).

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.
        run_id (int): Workflow run id.

    Returns:
        dict[str, Any]: Run metadata plus ``jobs`` list when present.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(method: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"id": 9} if method == "actions.get_workflow_run" else {"jobs": []}
        >>> out = asyncio.run(
        ...     workflow_run_logs(GithubSkillHooks(integration_call=_fake), repo="o/r", run_id=9)
        ... )
        >>> out["run_id"]
        9
    """
    owner, name = parse_github_repo(repo)
    run_payload = await github_integration_call(
        "actions.get_workflow_run",
        {"owner": owner, "repo": name, "run_id": int(run_id)},
        hooks=hooks,
    )
    jobs_payload = await github_integration_call(
        "actions.list_jobs_for_workflow_run",
        {"owner": owner, "repo": name, "run_id": int(run_id)},
        hooks=hooks,
    )
    jobs = jobs_payload.get("jobs") if isinstance(jobs_payload, dict) else []
    if not isinstance(jobs, list):
        jobs = []
    return {
        "owner": owner,
        "repo": name,
        "run_id": int(run_id),
        "run": run_payload,
        "jobs": jobs,
        "job_count": len(jobs),
    }


async def list_repo_secrets(
    hooks: GithubSkillHooks,
    *,
    repo: str,
) -> dict[str, Any]:
    """List repository Actions secret names (values never returned).

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.

    Returns:
        dict[str, Any]: Payload with ``secrets`` name rows.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"secrets": [{"name": "TOKEN"}]}
        >>> asyncio.run(list_repo_secrets(GithubSkillHooks(integration_call=_fake), repo="o/r"))["count"]
        1
    """
    owner, name = parse_github_repo(repo)
    payload = await github_integration_call(
        "actions.list_repo_secrets",
        {"owner": owner, "repo": name},
        hooks=hooks,
    )
    secrets = payload.get("secrets") or []
    if not isinstance(secrets, list):
        secrets = []
    return {"owner": owner, "repo": name, "secrets": secrets, "count": len(secrets)}


async def upsert_repo_secret(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    secret_name: str,
    encrypted_value: str,
) -> dict[str, Any]:
    """Create or update a repository Actions secret (encrypted value from proxy).

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.
        secret_name (str): Secret name.
        encrypted_value (str): Libsodium-encrypted secret payload for GitHub API.

    Returns:
        dict[str, Any]: Upsert acknowledgement payload.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"updated": True}
        >>> asyncio.run(
        ...     upsert_repo_secret(
        ...         GithubSkillHooks(integration_call=_fake),
        ...         repo="o/r",
        ...         secret_name="TOKEN",
        ...         encrypted_value="enc",
        ...     )
        ... )["secret_name"]
        'TOKEN'
    """
    owner, name = parse_github_repo(repo)
    payload = await github_integration_call(
        "actions.create_or_update_repo_secret",
        {
            "owner": owner,
            "repo": name,
            "secret_name": secret_name.strip(),
            "encrypted_value": encrypted_value,
        },
        hooks=hooks,
    )
    return {
        "owner": owner,
        "repo": name,
        "secret_name": secret_name.strip(),
        "result": payload,
    }


async def list_repo_variables(
    hooks: GithubSkillHooks,
    *,
    repo: str,
) -> dict[str, Any]:
    """List repository Actions variables.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.

    Returns:
        dict[str, Any]: Payload with ``variables`` list.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"variables": [{"name": "ENV", "value": "prod"}]}
        >>> asyncio.run(list_repo_variables(GithubSkillHooks(integration_call=_fake), repo="o/r"))["count"]
        1
    """
    owner, name = parse_github_repo(repo)
    payload = await github_integration_call(
        "actions.list_repo_variables",
        {"owner": owner, "repo": name},
        hooks=hooks,
    )
    variables = payload.get("variables") or []
    if not isinstance(variables, list):
        variables = []
    return {"owner": owner, "repo": name, "variables": variables, "count": len(variables)}


async def upsert_repo_variable(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    variable_name: str,
    value: str,
) -> dict[str, Any]:
    """Create or update a repository Actions variable.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.
        variable_name (str): Variable name.
        value (str): Plain variable value.

    Returns:
        dict[str, Any]: Upsert acknowledgement payload.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"updated": True}
        >>> asyncio.run(
        ...     upsert_repo_variable(
        ...         GithubSkillHooks(integration_call=_fake),
        ...         repo="o/r",
        ...         variable_name="ENV",
        ...         value="prod",
        ...     )
        ... )["variable_name"]
        'ENV'
    """
    owner, name = parse_github_repo(repo)
    payload = await github_integration_call(
        "actions.create_or_update_repo_variable",
        {
            "owner": owner,
            "repo": name,
            "name": variable_name.strip(),
            "value": value,
        },
        hooks=hooks,
    )
    return {
        "owner": owner,
        "repo": name,
        "variable_name": variable_name.strip(),
        "result": payload,
    }


async def list_environments(
    hooks: GithubSkillHooks,
    *,
    repo: str,
) -> dict[str, Any]:
    """List deployment environments for a repository.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.

    Returns:
        dict[str, Any]: Payload with ``environments`` list.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"environments": [{"name": "production"}]}
        >>> asyncio.run(list_environments(GithubSkillHooks(integration_call=_fake), repo="o/r"))["count"]
        1
    """
    owner, name = parse_github_repo(repo)
    payload = await github_integration_call(
        "actions.list_environments_for_repo",
        {"owner": owner, "repo": name},
        hooks=hooks,
    )
    environments = payload.get("environments") or []
    if not isinstance(environments, list):
        environments = []
    return {"owner": owner, "repo": name, "environments": environments, "count": len(environments)}


async def upsert_environment(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    environment_name: str,
    wait_timer: int | None = None,
) -> dict[str, Any]:
    """Create or update a deployment environment.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.
        environment_name (str): Environment name.
        wait_timer (int | None, optional): Optional wait timer minutes.

    Returns:
        dict[str, Any]: Upsert acknowledgement payload.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"name": "staging"}
        >>> asyncio.run(
        ...     upsert_environment(
        ...         GithubSkillHooks(integration_call=_fake),
        ...         repo="o/r",
        ...         environment_name="staging",
        ...     )
        ... )["environment_name"]
        'staging'
    """
    owner, name = parse_github_repo(repo)
    body: dict[str, Any] = {
        "owner": owner,
        "repo": name,
        "environment_name": environment_name.strip(),
    }
    if wait_timer is not None:
        body["wait_timer"] = int(wait_timer)
    payload = await github_integration_call(
        "actions.create_or_update_environment_for_repo",
        body,
        hooks=hooks,
    )
    return {
        "owner": owner,
        "repo": name,
        "environment_name": environment_name.strip(),
        "result": payload,
    }


async def create_deployment(
    hooks: GithubSkillHooks,
    *,
    repo: str,
    ref: str,
    environment: str,
    description: str | None = None,
) -> dict[str, Any]:
    """Trigger a GitHub deployment for ``ref`` in ``environment``.

    Args:
        hooks (GithubSkillHooks): Integration delegate.
        repo (str): ``owner/repo`` slug.
        ref (str): Git ref to deploy.
        environment (str): Target environment name.
        description (str | None, optional): Optional deployment description.

    Returns:
        dict[str, Any]: Created deployment payload.

    Examples:
        >>> import asyncio
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"id": 42}
        >>> asyncio.run(
        ...     create_deployment(
        ...         GithubSkillHooks(integration_call=_fake),
        ...         repo="o/r",
        ...         ref="main",
        ...         environment="production",
        ...     )
        ... )["environment"]
        'production'
    """
    owner, name = parse_github_repo(repo)
    body: dict[str, Any] = {
        "owner": owner,
        "repo": name,
        "ref": ref.strip(),
        "environment": environment.strip(),
        "auto_merge": False,
        "required_contexts": [],
    }
    if description:
        body["description"] = description.strip()
    payload = await github_integration_call("deployments.create", body, hooks=hooks)
    return {
        "owner": owner,
        "repo": name,
        "ref": ref,
        "environment": environment,
        "deployment": payload,
    }
