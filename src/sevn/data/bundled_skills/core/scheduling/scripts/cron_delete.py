#!/usr/bin/env python3
"""Bundled ``scheduling`` skill — delete cron job.

Module: sevn.data.bundled_skills.core.scheduling.scripts.cron_delete
Depends: argparse, sevn.lcm.script_cli, sevn.triggers.cron

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import open_workspace_db, write_error, write_ok
from sevn.triggers.cron import delete_cron_job


def main() -> int:
    """Run cron delete CLI.

    Returns:
        int: ``0`` on success; ``1`` when the job is missing.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    conn = open_workspace_db()
    try:
        deleted = delete_cron_job(conn, args.job_id)
    finally:
        conn.close()
    if not deleted:
        write_error(code="NOT_FOUND", error=f"unknown job_id: {args.job_id}")
        return 1
    write_ok({"job_id": args.job_id.strip(), "deleted": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
