#!/usr/bin/env python3
"""Bundled ``reddit-karma-loop`` — run discover → gate → draft (no posting)."""

from __future__ import annotations

import argparse
import json

from _common import dry_run_requested, load_template, workspace_path
from sevn.config.loader import load_workspace
from sevn.integrations.reddit_karma.loop import run_draft_loop
from sevn.lcm.script_cli import write_error, write_ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates-json",
        default=None,
        help="Optional JSON array of discovery candidates (omit for plan-only)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    dry = args.dry_run or dry_run_requested(argv)
    candidates: list[dict] | None = None
    if args.candidates_json:
        try:
            parsed = json.loads(args.candidates_json)
            if not isinstance(parsed, list):
                raise ValueError("candidates must be a JSON array")
            candidates = [row for row in parsed if isinstance(row, dict)]
        except (json.JSONDecodeError, ValueError) as exc:
            write_error(str(exc))
            return 1
    ws = workspace_path()
    cfg, _layout = load_workspace(start_dir=ws)
    template = load_template("comment_draft")
    result = run_draft_loop(ws, cfg, candidates=candidates, template=template, dry_run=dry)
    write_ok(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
