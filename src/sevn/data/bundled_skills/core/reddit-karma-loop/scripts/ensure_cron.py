#!/usr/bin/env python3
"""Bundled ``reddit-karma-loop`` — reconcile cron row via scheduling store."""

from __future__ import annotations

import argparse

from _common import workspace_path
from sevn.config.loader import load_workspace
from sevn.integrations.reddit_karma.scheduler import (
    REDDIT_KARMA_CRON_JOB_ID,
    reconcile_reddit_karma_cron_job,
)
from sevn.lcm.script_cli import open_workspace_db, write_ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    ws = workspace_path()
    cfg, _layout = load_workspace(start_dir=ws)
    with open_workspace_db(ws) as conn:
        reconcile_reddit_karma_cron_job(conn, cfg)
    write_ok({"job_id": REDDIT_KARMA_CRON_JOB_ID, "reconciled": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
