#!/usr/bin/env python3
"""Bundled ``reddit-karma-loop`` — draft-only post gate (D11; no auto_post)."""

from __future__ import annotations

import argparse

from _common import dry_run_requested, workspace_path
from _reddit_runtime import enforce_reddit_rate_limits, require_reddit_post_confirm
from sevn.config.loader import load_workspace
from sevn.integrations.reddit_karma.config import resolve_reddit_karma_config
from sevn.integrations.reddit_karma.log import RedditDecisionLog
from sevn.integrations.reddit_karma.runtime import strip_disallowed_links
from sevn.lcm.script_cli import write_error, write_ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subreddit", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--confirm", action="store_true", help="Operator approval for post")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    args.dry_run = args.dry_run or dry_run_requested(argv)
    ws = workspace_path()
    cfg, _layout = load_workspace(start_dir=ws)
    loop_cfg = resolve_reddit_karma_config(cfg)
    log = RedditDecisionLog(ws)
    blocked, reason = enforce_reddit_rate_limits(
        posts_today=log.posts_today_count(),
        max_posts_per_day=loop_cfg.max_comments_per_day,
        cooldown_seconds=loop_cfg.cooldown_seconds,
        seconds_since_last_post=log.seconds_since_last_post(),
    )
    if blocked:
        log.append(event="skip", skip_reason=reason, action="post_comment", url=args.url)
        write_error(code="RATE_LIMIT", error=reason or "rate limited")
        return 1
    body = strip_disallowed_links(args.body, allow_links=loop_cfg.allow_links)
    would_do = {
        "action": "post_comment",
        "subreddit": args.subreddit,
        "url": args.url,
        "body": body,
        "mode": "draft_only",
    }
    preview = require_reddit_post_confirm(args, would_do)
    if preview is not None:
        write_ok(preview)
        return 0
    if args.dry_run:
        write_ok({"dry_run": True, "would_do": would_do})
        return 0
    log.append(
        event="action",
        action="post_comment",
        url=args.url,
        outcome="recorded",
        draft={"body": body, "subreddit": args.subreddit},
    )
    write_ok(
        {
            "mode": "draft_only",
            "message": "Post recorded for operator follow-up via browser tool",
            "browser_plan": {
                "tool": "browser",
                "action": "social",
                "site": "reddit",
                "op": "reply",
                "url": args.url,
                "body": body,
            },
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
