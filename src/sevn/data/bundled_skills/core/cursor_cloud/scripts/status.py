#!/usr/bin/env python3
"""Bundled ``cursor_cloud`` skill — poll agent status."""

from __future__ import annotations

import argparse

from sevn.integrations.cursor_cloud.client import refresh_job_status
from sevn.integrations.cursor_cloud.errors import (
    CURSOR_API_ERROR,
    CURSOR_JOB_NOT_FOUND,
    CURSOR_VALIDATION_ERROR,
)
from sevn.integrations.cursor_cloud.jobs import get_job
from sevn.lcm.script_cli import open_workspace_db, write_error, write_ok
from sevn.lcm.script_cli import workspace_from_env


def main() -> int:
    """Run status CLI.

    Returns:
        int: Exit code.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", default=None)
    parser.add_argument("--cursor-agent-id", default=None)
    args = parser.parse_args()
    if not args.job_id and not args.cursor_agent_id:
        write_error(
            code=CURSOR_VALIDATION_ERROR,
            error="--job-id or --cursor-agent-id is required",
        )
        return 1

    workspace = workspace_from_env()
    conn = open_workspace_db(workspace)
    try:
        job = get_job(
            conn,
            job_id=args.job_id,
            cursor_agent_id=args.cursor_agent_id,
        )
        if job is None:
            write_error(code=CURSOR_JOB_NOT_FOUND, error="job not found")
            return 1
        try:
            job = refresh_job_status(conn, job)
        except RuntimeError as exc:
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
            "pr_url": job.pr_url,
            "branch": job.branch,
            "latest_run_id": job.latest_run_id,
            "result_text": job.result_text,
            "artifact_count": job.artifact_count,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
