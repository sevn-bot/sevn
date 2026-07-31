#!/usr/bin/env python3
"""Bundled ``reddit-karma-loop`` — emit browser discovery plan (D10).

Module: sevn.data.bundled_skills.core.reddit-karma-loop.scripts.discover
Depends: argparse, sevn.config.loader, sevn.integrations.reddit_karma.loop

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from _common import dry_run_requested, workspace_path
from sevn.config.loader import load_workspace
from sevn.integrations.reddit_karma.config import resolve_reddit_karma_config
from sevn.integrations.reddit_karma.loop import build_discovery_browser_plan
from sevn.lcm.script_cli import write_ok


def main(argv: list[str] | None = None) -> int:
    """Print the browser discovery plan for Reddit (``site=reddit``)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subreddit", default=None, help="Target subreddit (without r/)")
    parser.add_argument("--query", default=None, help="Search query override")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    dry = args.dry_run or dry_run_requested(argv)
    ws = workspace_path()
    cfg, _layout = load_workspace(start_dir=ws)
    loop_cfg = resolve_reddit_karma_config(cfg)
    plan = build_discovery_browser_plan(loop_cfg, subreddit=args.subreddit, query=args.query)
    write_ok({"dry_run": dry, "discovery_plan": plan, "medium": "browser", "site": "reddit"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
