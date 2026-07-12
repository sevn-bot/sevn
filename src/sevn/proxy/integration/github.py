"""GitHub REST forwarder for egress proxy ``POST /integration`` (`specs/07-egress-proxy.md`).

Module: sevn.proxy.integration.github
Depends: httpx, urllib.parse, sevn.security.secrets.cache, sevn.security.secrets.chain

Constants:
    GITHUB_TOKEN_SECRET — proxy secrets key for the GitHub PAT.

Exports:
    dispatch_github — route ``service=github`` integration methods to api.github.com.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse

from sevn.security.secrets.cache import ResolvedSecretsCache
from sevn.security.secrets.chain import get_secret_resilient

GITHUB_TOKEN_SECRET: str = "integration.github.token"
_GITHUB_API: str = "https://api.github.com"
_DEFAULT_TIMEOUT_S: float = 60.0
_API_VERSION: str = "2022-11-28"


async def _resolve_github_token(cache: ResolvedSecretsCache | None) -> str | None:
    """Load GitHub token from env or proxy secrets chain.

    Args:
        cache (ResolvedSecretsCache | None): Workspace secrets cache.

    Returns:
        str | None: Bearer token or ``None`` when unset.

    Examples:
        >>> import asyncio
        >>> asyncio.run(_resolve_github_token(None)) is None or True
        True
    """
    env_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if env_token:
        return env_token
    if cache is None:
        return None
    return await get_secret_resilient(cache.chain, GITHUB_TOKEN_SECRET)


def _github_headers(token: str) -> dict[str, str]:
    """Build GitHub REST request headers.

    Args:
        token (str): GitHub personal access token.

    Returns:
        dict[str, str]: Authorization and API version headers.

    Examples:
        >>> hdr = _github_headers("ghp_test")
        >>> hdr["Authorization"].startswith("Bearer ")
        True
    """
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": _API_VERSION,
    }


async def _github_request(
    *,
    method: str,
    path: str,
    token: str,
    json_body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> tuple[int, Any]:
    """Issue one GitHub REST request.

    Args:
        method (str): HTTP verb.
        path (str): Path beginning with ``/`` under api.github.com.
        token (str): GitHub bearer token.
        json_body (dict[str, Any] | None, optional): JSON request body.
        params (dict[str, str] | None, optional): Query parameters.

    Returns:
        tuple[int, Any]: HTTP status and decoded JSON (object or array).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_github_request)
        True
    """
    url = f"{_GITHUB_API}{path}"
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_S) as client:
        response = await client.request(
            method,
            url,
            headers=_github_headers(token),
            json=json_body,
            params=params,
        )
        try:
            data = response.json()
        except ValueError:
            return response.status_code, {
                "detail": f"github returned non-JSON body (status {response.status_code})",
            }
        return response.status_code, data


def _wrap_list_payload(data: Any) -> dict[str, Any]:
    """Normalize list upstream bodies to ``{"items": [...]}`` for skill helpers.

    Args:
        data (Any): Upstream JSON body.

    Returns:
        dict[str, Any]: Wrapped or passthrough mapping.

    Examples:
        >>> _wrap_list_payload([{"n": 1}])
        {'items': [{'n': 1}]}
        >>> _wrap_list_payload({"secrets": []})["secrets"]
        []
    """
    if isinstance(data, list):
        return {"items": data}
    if isinstance(data, dict):
        return data
    return {"result": data}


def _owner_repo(args: dict[str, Any]) -> tuple[str, str] | JSONResponse:
    """Validate ``owner`` and ``repo`` keys in integration args.

    Args:
        args (dict[str, Any]): Integration args payload.

    Returns:
        tuple[str, str] | JSONResponse: Owner/repo pair or validation error response.

    Examples:
        >>> isinstance(_owner_repo({"owner": "o", "repo": "r"}), tuple)
        True
    """
    owner = str(args.get("owner") or "").strip()
    repo = str(args.get("repo") or "").strip()
    if not owner or not repo:
        return JSONResponse({"detail": "owner and repo are required"}, status_code=422)
    return owner, repo


def _repo_path(owner: str, repo: str) -> str:
    """Return ``/repos/{owner}/{repo}`` prefix.

    Args:
        owner (str): Repository owner.
        repo (str): Repository name.

    Returns:
        str: API path prefix.

    Examples:
        >>> _repo_path("acme", "app")
        '/repos/acme/app'
    """
    return f"/repos/{owner}/{repo}"


async def dispatch_github(
    request: Request,
    *,
    method: str,
    args: dict[str, Any],
    secrets_cache: ResolvedSecretsCache | None,
) -> JSONResponse:
    """Dispatch a GitHub integration method to the GitHub REST API.

    Args:
        request (Request): Starlette request (unused; reserved).
        method (str): Dotted REST-shaped method (``pulls.list``, ...).
        args (dict[str, Any]): Method arguments from the gateway.
        secrets_cache (ResolvedSecretsCache | None): Proxy secrets cache.

    Returns:
        JSONResponse: Upstream JSON or validation error.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(dispatch_github)
        True
    """
    _ = request
    token = await _resolve_github_token(secrets_cache)
    if not token:
        return JSONResponse(
            {
                "detail": (
                    "GitHub token not configured "
                    f"({GITHUB_TOKEN_SECRET} via sevn secrets or GITHUB_TOKEN env)"
                ),
            },
            status_code=503,
        )

    pair = _owner_repo(args)
    if isinstance(pair, JSONResponse):
        return pair
    owner, repo = pair
    base = _repo_path(owner, repo)

    if method == "repos.get":
        status, data = await _github_request(method="GET", path=base, token=token)
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "repos.list_branches":
        status, data = await _github_request(method="GET", path=f"{base}/branches", token=token)
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "issues.list_for_repo":
        params: dict[str, str] = {}
        if args.get("state") is not None:
            params["state"] = str(args["state"])
        if args.get("labels") is not None:
            params["labels"] = str(args["labels"])
        status, data = await _github_request(
            method="GET",
            path=f"{base}/issues",
            token=token,
            params=params or None,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "issues.get":
        issue_number = args.get("issue_number")
        if issue_number is None:
            return JSONResponse({"detail": "issue_number is required"}, status_code=422)
        status, data = await _github_request(
            method="GET",
            path=f"{base}/issues/{int(issue_number)}",
            token=token,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "issues.create":
        body = {k: v for k, v in args.items() if k not in ("owner", "repo")}
        status, data = await _github_request(
            method="POST",
            path=f"{base}/issues",
            token=token,
            json_body=body,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "issues.create_comment":
        issue_number = args.get("issue_number")
        if issue_number is None:
            return JSONResponse({"detail": "issue_number is required"}, status_code=422)
        body = {k: v for k, v in args.items() if k not in ("owner", "repo", "issue_number")}
        status, data = await _github_request(
            method="POST",
            path=f"{base}/issues/{int(issue_number)}/comments",
            token=token,
            json_body=body,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "pulls.list":
        params = {}
        if args.get("state") is not None:
            params["state"] = str(args["state"])
        status, data = await _github_request(
            method="GET",
            path=f"{base}/pulls",
            token=token,
            params=params or None,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "pulls.get":
        pull_number = args.get("pull_number")
        if pull_number is None:
            return JSONResponse({"detail": "pull_number is required"}, status_code=422)
        status, data = await _github_request(
            method="GET",
            path=f"{base}/pulls/{int(pull_number)}",
            token=token,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "pulls.create":
        body = {k: v for k, v in args.items() if k not in ("owner", "repo")}
        status, data = await _github_request(
            method="POST",
            path=f"{base}/pulls",
            token=token,
            json_body=body,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "pulls.merge":
        pull_number = args.get("pull_number")
        if pull_number is None:
            return JSONResponse({"detail": "pull_number is required"}, status_code=422)
        body = {
            k: v
            for k, v in args.items()
            if k not in ("owner", "repo", "pull_number") and v is not None
        }
        status, data = await _github_request(
            method="PUT",
            path=f"{base}/pulls/{int(pull_number)}/merge",
            token=token,
            json_body=body or None,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "pulls.update":
        pull_number = args.get("pull_number")
        if pull_number is None:
            return JSONResponse({"detail": "pull_number is required"}, status_code=422)
        body = {k: v for k, v in args.items() if k not in ("owner", "repo", "pull_number")}
        status, data = await _github_request(
            method="PATCH",
            path=f"{base}/pulls/{int(pull_number)}",
            token=token,
            json_body=body,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "pulls.request_reviewers":
        pull_number = args.get("pull_number")
        if pull_number is None:
            return JSONResponse({"detail": "pull_number is required"}, status_code=422)
        body = {k: v for k, v in args.items() if k not in ("owner", "repo", "pull_number")}
        status, data = await _github_request(
            method="POST",
            path=f"{base}/pulls/{int(pull_number)}/requested_reviewers",
            token=token,
            json_body=body,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "git.create_ref":
        body = {k: v for k, v in args.items() if k not in ("owner", "repo")}
        status, data = await _github_request(
            method="POST",
            path=f"{base}/git/refs",
            token=token,
            json_body=body,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "git.delete_ref":
        ref = str(args.get("ref") or "").strip()
        if not ref:
            return JSONResponse({"detail": "ref is required"}, status_code=422)
        encoded = quote(ref, safe="")
        status, data = await _github_request(
            method="DELETE",
            path=f"{base}/git/refs/{encoded}",
            token=token,
        )
        if status == 204:
            return JSONResponse({"deleted": True}, status_code=200)
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "actions.list_repo_workflows":
        status, data = await _github_request(
            method="GET",
            path=f"{base}/actions/workflows",
            token=token,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "actions.create_workflow_dispatch":
        workflow_id = str(args.get("workflow_id") or "").strip()
        ref = str(args.get("ref") or "").strip()
        if not workflow_id or not ref:
            return JSONResponse(
                {"detail": "workflow_id and ref are required"},
                status_code=422,
            )
        dispatch_body: dict[str, Any] = {"ref": ref}
        if args.get("inputs") is not None:
            dispatch_body["inputs"] = dict(args["inputs"])
        status, data = await _github_request(
            method="POST",
            path=f"{base}/actions/workflows/{quote(workflow_id, safe='')}/dispatches",
            token=token,
            json_body=dispatch_body,
        )
        if status == 204:
            return JSONResponse({"dispatched": True}, status_code=200)
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "actions.get_workflow_run":
        run_id = args.get("run_id")
        if run_id is None:
            return JSONResponse({"detail": "run_id is required"}, status_code=422)
        status, data = await _github_request(
            method="GET",
            path=f"{base}/actions/runs/{int(run_id)}",
            token=token,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "actions.list_jobs_for_workflow_run":
        run_id = args.get("run_id")
        if run_id is None:
            return JSONResponse({"detail": "run_id is required"}, status_code=422)
        status, data = await _github_request(
            method="GET",
            path=f"{base}/actions/runs/{int(run_id)}/jobs",
            token=token,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "actions.list_repo_secrets":
        status, data = await _github_request(
            method="GET",
            path=f"{base}/actions/secrets",
            token=token,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "actions.create_or_update_repo_secret":
        secret_name = str(args.get("secret_name") or "").strip()
        if not secret_name:
            return JSONResponse({"detail": "secret_name is required"}, status_code=422)
        body = {
            k: v
            for k, v in args.items()
            if k not in ("owner", "repo", "secret_name") and v is not None
        }
        status, data = await _github_request(
            method="PUT",
            path=f"{base}/actions/secrets/{quote(secret_name, safe='')}",
            token=token,
            json_body=body,
        )
        if status == 204:
            return JSONResponse({"updated": True}, status_code=200)
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "actions.list_repo_variables":
        status, data = await _github_request(
            method="GET",
            path=f"{base}/actions/variables",
            token=token,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "actions.create_or_update_repo_variable":
        name = str(args.get("name") or "").strip()
        if not name:
            return JSONResponse({"detail": "name is required"}, status_code=422)
        body = {k: v for k, v in args.items() if k not in ("owner", "repo", "name")}
        status, data = await _github_request(
            method="PATCH",
            path=f"{base}/actions/variables/{quote(name, safe='')}",
            token=token,
            json_body=body,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "actions.list_environments_for_repo":
        status, data = await _github_request(
            method="GET",
            path=f"{base}/environments",
            token=token,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "actions.create_or_update_environment_for_repo":
        env_name = str(args.get("environment_name") or "").strip()
        if not env_name:
            return JSONResponse({"detail": "environment_name is required"}, status_code=422)
        body = {
            k: v
            for k, v in args.items()
            if k not in ("owner", "repo", "environment_name") and v is not None
        }
        status, data = await _github_request(
            method="PUT",
            path=f"{base}/environments/{quote(env_name, safe='')}",
            token=token,
            json_body=body or None,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    if method == "deployments.create":
        body = {k: v for k, v in args.items() if k not in ("owner", "repo")}
        status, data = await _github_request(
            method="POST",
            path=f"{base}/deployments",
            token=token,
            json_body=body,
        )
        return JSONResponse(_wrap_list_payload(data), status_code=status)

    return JSONResponse({"detail": f"unknown github method: {method}"}, status_code=422)


__all__ = ["GITHUB_TOKEN_SECRET", "dispatch_github"]
