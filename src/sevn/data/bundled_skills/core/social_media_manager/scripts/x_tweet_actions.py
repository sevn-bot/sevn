#!/usr/bin/env python3
"""Tweet-action facade scripts (like / retweet / create / …) via ``x_ops``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import x_ops as x_ops_cli  # noqa: E402

_ACTIONS = (
    "like_tweet",
    "unlike_tweet",
    "retweet",
    "delete_retweet",
    "bookmark",
    "delete_bookmark",
    "create_tweet_or_reply",
    "create_quote_tweet",
    "create_tweet_thread",
    "delete_tweets",
    "post_tweet_auto_cookie",
)


def main(argv: list[str] | None = None) -> int:
    """CLI entry for tweet-action facade ops.

    Args:
        argv (list[str] | None): Optional argv override.

    Returns:
        int: Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("op", choices=_ACTIONS)
    parser.add_argument("--tweet-id", default=None)
    parser.add_argument("--text", default=None)
    parser.add_argument("--task", default=None, help="Full JSON task (overrides flags)")
    parser.add_argument("--medium", default=None)
    parser.add_argument("--site", default="x")
    parser.add_argument("--dry-run", "-n", action="store_true")
    ns = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if ns.task:
        task_json = ns.task
    else:
        task: dict[str, object] = {}
        if ns.tweet_id:
            task["tweet_id"] = ns.tweet_id
        if ns.text:
            task["text"] = ns.text
        task_json = json.dumps(task)
    forwarded = [ns.op, "--task", task_json, "--site", ns.site]
    if ns.medium:
        forwarded.extend(["--medium", ns.medium])
    if ns.dry_run:
        forwarded.append("--dry-run")
    return int(x_ops_cli.main(forwarded))


if __name__ == "__main__":
    raise SystemExit(main())
