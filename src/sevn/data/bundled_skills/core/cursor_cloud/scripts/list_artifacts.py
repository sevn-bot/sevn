#!/usr/bin/env python3
"""Bundled ``cursor_cloud`` skill — list or download Cursor agent artifacts."""

from __future__ import annotations

import argparse

from sevn.integrations.cursor_cloud.client import artifact_download_url, list_artifacts
from sevn.integrations.cursor_cloud.errors import (
    CURSOR_API_ERROR,
    CURSOR_JOB_NOT_FOUND,
    CURSOR_VALIDATION_ERROR,
)
from sevn.integrations.cursor_cloud.jobs import get_job
from sevn.lcm.script_cli import open_workspace_db, write_error, write_ok
from sevn.lcm.script_cli import workspace_from_env


def main() -> int:
    """Run list_artifacts CLI.

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
    parser.add_argument("--download-path", default=None)
    args = parser.parse_args()
    if not args.job_id and not args.cursor_agent_id:
        write_error(
            code=CURSOR_VALIDATION_ERROR,
            error="--job-id or --cursor-agent-id is required",
        )
        return 1

    conn = open_workspace_db(workspace_from_env())
    try:
        job = get_job(
            conn,
            job_id=args.job_id,
            cursor_agent_id=args.cursor_agent_id,
        )
        if job is None:
            write_error(code=CURSOR_JOB_NOT_FOUND, error="job not found")
            return 1
        agent_id = job.cursor_agent_id
        try:
            if args.download_path and args.download_path.strip():
                payload = artifact_download_url(agent_id, args.download_path.strip())
                write_ok({"download": payload, "agent_id": agent_id})
                return 0
            payload = list_artifacts(agent_id)
        except RuntimeError as exc:
            write_error(code=CURSOR_API_ERROR, error=str(exc))
            return 1
    finally:
        conn.close()

    write_ok({"artifacts": payload, "agent_id": agent_id})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
