#!/usr/bin/env python3
"""Bundled ``cursor_cloud`` skill — list local jobs."""

from __future__ import annotations

import argparse

from sevn.integrations.cursor_cloud.jobs import list_workspace_jobs
from sevn.lcm.script_cli import open_workspace_db, session_key_from, write_ok
from sevn.lcm.script_cli import workspace_from_env


def main() -> int:
    """Run list_jobs CLI.

    Returns:
        int: ``0`` on success.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-key", default=None)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    conn = open_workspace_db(workspace_from_env())
    try:
        jobs = list_workspace_jobs(
            conn,
            session_key=session_key_from(cli_value=args.session_key) or None,
            limit=args.limit,
        )
    finally:
        conn.close()

    write_ok(
        {
            "jobs": [
                {
                    "job_id": j.job_id,
                    "cursor_agent_id": j.cursor_agent_id,
                    "status": j.status,
                    "agent_url": j.agent_url,
                    "pr_url": j.pr_url,
                    "repo_url": j.repo_url,
                    "prompt": j.prompt[:200],
                    "created_at": j.created_at,
                }
                for j in jobs
            ],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
