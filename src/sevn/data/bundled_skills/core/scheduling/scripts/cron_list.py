#!/usr/bin/env python3
"""Bundled ``scheduling`` skill — list cron jobs.

Module: sevn.data.bundled_skills.core.scheduling.scripts.cron_list
Depends: argparse, sevn.lcm.script_cli, sevn.triggers.cron

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import open_workspace_db, write_ok
from sevn.triggers.cron import cron_job_to_list_dict, list_cron_jobs


def main() -> int:
    """Run cron list CLI.

    Returns:
        int: ``0`` on success.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--enabled-only", action="store_true")
    args = parser.parse_args()
    conn = open_workspace_db()
    try:
        jobs = list_cron_jobs(conn)
        if args.enabled_only:
            jobs = [j for j in jobs if j.enabled]
        payload = {
            "jobs": [cron_job_to_list_dict(j) for j in jobs],
            "count": len(jobs),
        }
    finally:
        conn.close()
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
