#!/usr/bin/env python3
"""Bundled ``cursor_cloud`` skill — launch Cursor Cloud Agent.

Module: sevn.data.bundled_skills.core.cursor_cloud.scripts.launch
Depends: argparse, sevn.integrations.cursor_cloud
"""

from __future__ import annotations

import argparse
import json

from sevn.integrations.cursor_cloud.client import (
    create_cloud_agent,
    parse_mcp_servers_json,
    parse_subagents_json,
)
from sevn.integrations.cursor_cloud.config import load_cursor_cloud_settings
from sevn.integrations.cursor_cloud.errors import CURSOR_API_ERROR, CURSOR_VALIDATION_ERROR
from sevn.lcm.script_cli import open_workspace_db, session_key_from, write_error, write_ok
from sevn.lcm.script_cli import workspace_from_env


def main() -> int:
    """Run launch CLI.

    Returns:
        int: ``0`` on success; ``1`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--repo-url", default=None)
    parser.add_argument("--ref", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--auto-create-pr", action="store_true", default=None)
    parser.add_argument("--no-auto-create-pr", action="store_true")
    parser.add_argument("--mcp-profile", default=None)
    parser.add_argument("--mcp-servers-json", default=None)
    parser.add_argument("--subagents-json", default=None)
    parser.add_argument("--session-key", default=None)
    args = parser.parse_args()

    workspace = workspace_from_env()
    settings, _cfg = load_cursor_cloud_settings(workspace)
    if not settings.enabled:
        write_error(
            code=CURSOR_VALIDATION_ERROR,
            error="skills.cursor_cloud.enabled is false",
        )
        return 1

    repo_url = (args.repo_url or settings.default_repo_url or "").strip()
    if not repo_url:
        write_error(
            code=CURSOR_VALIDATION_ERROR,
            error="--repo-url or skills.cursor_cloud.default_repo_url is required",
        )
        return 1

    starting_ref = (args.ref or settings.default_ref).strip()
    auto_pr: bool | None = None
    if args.auto_create_pr:
        auto_pr = True
    elif args.no_auto_create_pr:
        auto_pr = False

    try:
        mcp_servers = parse_mcp_servers_json(args.mcp_servers_json)
        subagents = parse_subagents_json(args.subagents_json)
    except (ValueError, json.JSONDecodeError) as exc:
        write_error(code=CURSOR_VALIDATION_ERROR, error=str(exc))
        return 1

    conn = open_workspace_db(workspace)
    try:
        job = create_cloud_agent(
            conn,
            workspace,
            prompt=args.prompt,
            repo_url=repo_url,
            starting_ref=starting_ref,
            session_key=session_key_from(cli_value=args.session_key),
            model=args.model,
            auto_create_pr=auto_pr,
            mcp_profile=args.mcp_profile,
            mcp_servers=mcp_servers,
            subagents=subagents,
        )
    except (RuntimeError, ValueError) as exc:
        write_error(code=CURSOR_API_ERROR, error=str(exc))
        return 1
    finally:
        conn.close()

    write_ok(
        {
            "job_id": job.job_id,
            "cursor_agent_id": job.cursor_agent_id,
            "status": job.status,
            "agent_url": job.agent_url,
            "latest_run_id": job.latest_run_id,
            "repo_url": job.repo_url,
            "starting_ref": job.starting_ref,
        },
        message="Cursor Cloud Agent launched",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
