#!/usr/bin/env python3
"""Bundled ``reddit-karma-loop`` — evaluate one candidate through the quality gate."""

from __future__ import annotations

import argparse
import json

from _common import workspace_path
from sevn.config.loader import load_workspace
from sevn.integrations.reddit_karma.config import resolve_reddit_karma_config
from sevn.integrations.reddit_karma.quality_gate import candidate_from_dict, evaluate_candidate
from sevn.lcm.script_cli import write_error, write_ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-json", required=True, help="JSON object for one candidate")
    args = parser.parse_args(argv)
    try:
        raw = json.loads(args.candidate_json)
        if not isinstance(raw, dict):
            raise ValueError("candidate must be a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        write_error(str(exc))
        return 1
    ws = workspace_path()
    cfg, _layout = load_workspace(start_dir=ws)
    loop_cfg = resolve_reddit_karma_config(cfg)
    allowed = frozenset(s.lower() for s in loop_cfg.subreddits)
    candidate = candidate_from_dict(raw, allowed_subreddits=allowed)
    accepted, skip_reason = evaluate_candidate(candidate)
    write_ok({"accepted": accepted, "skip_reason": skip_reason, "candidate": raw})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
