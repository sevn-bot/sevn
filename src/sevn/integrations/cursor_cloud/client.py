"""Cursor Cloud Agents API client via egress proxy.

Module: sevn.integrations.cursor_cloud.client
Depends: sevn.integrations.cursor_cloud.jobs, sevn.integrations.proxy_client

Exports:
    create_cloud_agent — launch and persist job.
    get_agent — fetch agent metadata.
    get_run — fetch run status.
    list_artifacts — list agent artifacts.
    artifact_download_url — presigned download URL.
    refresh_job_status — poll and update SQLite job.
    parse_mcp_servers_json — parse CLI MCP JSON.
    parse_subagents_json — parse CLI subagents JSON.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sevn.integrations.cursor_cloud.config import load_cursor_cloud_settings
from sevn.integrations.cursor_cloud.jobs import (
    CursorCloudJob,
    insert_job,
    update_job,
)

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path
from sevn.integrations.proxy_client import integration_post_sync

_CURSOR_SERVICE = "cursor"


def _extract_agent_from_create(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize create response to agent dict.

    Args:
        payload (dict[str, Any]): Proxy/upstream JSON.

    Returns:
        dict[str, Any]: Agent object.

    Raises:
        ValueError: When agent id is missing.

    Examples:
        >>> _extract_agent_from_create({"agent": {"id": "bc-1"}})["id"]
        'bc-1'
    """
    agent = payload.get("agent")
    if isinstance(agent, dict) and agent.get("id"):
        return agent
    if payload.get("id"):
        return payload
    msg = "cursor agents.create response missing agent id"
    raise ValueError(msg)


def create_cloud_agent(
    conn: sqlite3.Connection,
    workspace: Path,
    *,
    prompt: str,
    repo_url: str,
    starting_ref: str,
    session_key: str = "",
    model: str | None = None,
    auto_create_pr: bool | None = None,
    mcp_profile: str | None = None,
    mcp_servers: list[dict[str, Any]] | None = None,
    subagents: list[dict[str, Any]] | None = None,
) -> CursorCloudJob:
    """Launch a Cursor cloud agent and persist a local job row.

    Args:
        conn (sqlite3.Connection): Workspace SQLite (migrated).
        workspace (Path): Content root for config lookup.
        prompt (str): Task instruction.
        repo_url (str): GitHub/GitLab repository URL.
        starting_ref (str): Branch or ref.
        session_key (str): Session attribution.
        model (str | None): Model id override.
        auto_create_pr (bool | None): PR flag override.
        mcp_profile (str | None): Named MCP profile for proxy expansion.
        mcp_servers (list[dict[str, Any]] | None): Inline MCP servers.
        subagents (list[dict[str, Any]] | None): Custom subagent definitions.

    Returns:
        CursorCloudJob: Persisted job after create.

    Raises:
        RuntimeError: When proxy call fails.
        ValueError: When response is invalid.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(create_cloud_agent)
        True
    """
    settings, _cfg = load_cursor_cloud_settings(workspace)
    model_id = (model or settings.default_model).strip()
    create_pr = settings.auto_create_pr if auto_create_pr is None else auto_create_pr
    args: dict[str, Any] = {
        "prompt": {"text": prompt.strip()},
        "repos": [{"url": repo_url.strip(), "startingRef": starting_ref.strip()}],
        "model": {"id": model_id},
        "autoCreatePR": bool(create_pr),
    }
    profile = mcp_profile or settings.default_mcp_profile
    if profile:
        args["mcp_profile"] = profile.strip()
    if mcp_servers:
        args["mcpServers"] = mcp_servers
    if subagents:
        args["subagents"] = subagents

    payload = integration_post_sync(service=_CURSOR_SERVICE, method="agents.create", args=args)
    agent = _extract_agent_from_create(payload)
    agent_id = str(agent["id"])
    run = payload.get("run")
    run_id = str(run["id"]) if isinstance(run, dict) and run.get("id") else None
    status = str(agent.get("status") or "CREATING")
    agent_url = str(agent.get("url") or f"https://cursor.com/agents/{agent_id}")

    return insert_job(
        conn,
        cursor_agent_id=agent_id,
        session_key=session_key,
        prompt=prompt.strip(),
        repo_url=repo_url.strip(),
        starting_ref=starting_ref.strip(),
        status=status,
        agent_url=agent_url,
        latest_run_id=run_id,
    )


def get_agent(agent_id: str) -> dict[str, Any]:
    """Fetch Cursor agent metadata.

    Args:
        agent_id (str): ``bc-`` agent id.

    Returns:
        dict[str, Any]: Agent JSON.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(get_agent)
        True
    """
    return integration_post_sync(
        service=_CURSOR_SERVICE,
        method="agents.get",
        args={"id": agent_id},
    )


def get_run(agent_id: str, run_id: str) -> dict[str, Any]:
    """Fetch one agent run.

    Args:
        agent_id (str): Agent id.
        run_id (str): Run id.

    Returns:
        dict[str, Any]: Run JSON.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(get_run)
        True
    """
    return integration_post_sync(
        service=_CURSOR_SERVICE,
        method="runs.get",
        args={"agent_id": agent_id, "run_id": run_id},
    )


def list_artifacts(agent_id: str) -> dict[str, Any]:
    """List artifacts for an agent.

    Args:
        agent_id (str): Agent id.

    Returns:
        dict[str, Any]: Artifacts list payload.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(list_artifacts)
        True
    """
    return integration_post_sync(
        service=_CURSOR_SERVICE,
        method="artifacts.list",
        args={"agent_id": agent_id},
    )


def artifact_download_url(agent_id: str, path: str) -> dict[str, Any]:
    """Resolve a presigned artifact download URL.

    Args:
        agent_id (str): Agent id.
        path (str): Relative artifact path.

    Returns:
        dict[str, Any]: Payload with ``url`` key.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(artifact_download_url)
        True
    """
    return integration_post_sync(
        service=_CURSOR_SERVICE,
        method="artifacts.download",
        args={"agent_id": agent_id, "path": path},
    )


def _pr_and_branch_from_run(run: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Extract PR URL, branch, and result text from a run payload.

    Args:
        run (dict[str, Any]): Run JSON.

    Returns:
        tuple[str | None, str | None, str | None]: ``(pr_url, branch, result_text)``.

    Examples:
        >>> _pr_and_branch_from_run({"result": "done", "git": {"branches": [{"prUrl": "http://p"}]}})
        ('http://p', None, 'done')
    """
    result_text = run.get("result")
    result_str = str(result_text) if result_text is not None else None
    git = run.get("git")
    if not isinstance(git, dict):
        return None, None, result_str
    branches = git.get("branches")
    if not isinstance(branches, list) or not branches:
        return None, None, result_str
    first = branches[0]
    if not isinstance(first, dict):
        return None, None, result_str
    pr = first.get("prUrl")
    branch = first.get("branch")
    return (
        str(pr) if isinstance(pr, str) and pr else None,
        str(branch) if isinstance(branch, str) and branch else None,
        result_str,
    )


def refresh_job_status(conn: sqlite3.Connection, job: CursorCloudJob) -> CursorCloudJob:
    """Poll Cursor for agent + latest run and update the job row.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        job (CursorCloudJob): Existing job.

    Returns:
        CursorCloudJob: Updated job.

    Raises:
        RuntimeError: When API calls fail.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(refresh_job_status)
        True
    """
    agent = get_agent(job.cursor_agent_id)
    status = str(agent.get("status") or job.status)
    agent_url = str(agent.get("url") or job.agent_url or "")
    run_id = str(agent.get("latestRunId") or job.latest_run_id or "")
    pr_url: str | None = job.pr_url
    branch: str | None = job.branch
    result_text: str | None = job.result_text
    artifact_count = job.artifact_count

    if run_id:
        try:
            run = get_run(job.cursor_agent_id, run_id)
            status = str(run.get("status") or status)
            pr, br, res = _pr_and_branch_from_run(run)
            pr_url = pr or pr_url
            branch = br or branch
            result_text = res or result_text
        except RuntimeError:
            pass

    try:
        arts = list_artifacts(job.cursor_agent_id)
        items = arts.get("items")
        if isinstance(items, list):
            artifact_count = len(items)
    except RuntimeError:
        pass

    updated = update_job(
        conn,
        job.job_id,
        status=status,
        latest_run_id=run_id or None,
        pr_url=pr_url,
        branch=branch,
        agent_url=agent_url or None,
        result_text=result_text,
        artifact_count=artifact_count,
    )
    return updated if updated is not None else job


def parse_mcp_servers_json(raw: str | None) -> list[dict[str, Any]] | None:
    """Parse CLI ``--mcp-servers-json`` into a list.

    Args:
        raw (str | None): JSON array string.

    Returns:
        list[dict[str, Any]] | None: Parsed servers or ``None``.

    Raises:
        ValueError: When JSON is invalid.

    Examples:
        >>> parse_mcp_servers_json('[{"name":"x","url":"https://example.com"}]')[0]["name"]
        'x'
    """
    if not raw or not raw.strip():
        return None
    data = json.loads(raw.strip())
    if not isinstance(data, list):
        msg = "mcp-servers-json must be a JSON array"
        raise ValueError(msg)
    return [item for item in data if isinstance(item, dict)]


def parse_subagents_json(raw: str | None) -> list[dict[str, Any]] | None:
    """Parse CLI ``--subagents-json``.

    Args:
        raw (str | None): JSON array string.

    Returns:
        list[dict[str, Any]] | None: Parsed subagents or ``None``.

    Raises:
        ValueError: When JSON is invalid.

    Examples:
        >>> parse_subagents_json(None) is None
        True
    """
    if not raw or not raw.strip():
        return None
    data = json.loads(raw.strip())
    if not isinstance(data, list):
        msg = "subagents-json must be a JSON array"
        raise ValueError(msg)
    return [item for item in data if isinstance(item, dict)]
