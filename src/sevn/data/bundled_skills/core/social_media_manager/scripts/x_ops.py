#!/usr/bin/env python3
"""Call a unified X ops facade function (browser | twexapi) with a JSON task.

Envelope: ``{ok, medium, op, data, error?, code?}``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import content_root_from_env, dry_run_requested  # noqa: E402

from sevn.config.loader import load_workspace  # noqa: E402
from sevn.integrations.social_media import x_ops  # noqa: E402
from sevn.lcm.script_cli import write_error, write_ok  # noqa: E402

_FACADE_OPS: tuple[str, ...] = (
    "advanced_search_page",
    "search_hashtags",
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
    "get_users_by_usernames",
    "follow_user",
    "fetch_article_markdown",
    "home_timeline_collect",
    "session_status",
)


def _parse_task(raw: str | None) -> dict[str, Any]:
    """Parse optional ``--task`` JSON object.

    Args:
        raw (str | None): JSON text.

    Returns:
        dict[str, Any]: Task object.

    Raises:
        SystemExit: When JSON is invalid.
    """
    if raw is None or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"invalid --task JSON: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if not isinstance(value, dict):
        print("--task must be a JSON object", file=sys.stderr)
        raise SystemExit(2)
    return {str(k): v for k, v in value.items()}


def main(argv: list[str] | None = None) -> int:
    """CLI entry.

    Args:
        argv (list[str] | None): Optional argv override.

    Returns:
        int: Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("op", choices=_FACADE_OPS, help="Facade op name")
    parser.add_argument("--task", default=None, help="JSON object task payload")
    parser.add_argument("--medium", default=None, help="Override medium (browser|twexapi)")
    parser.add_argument("--site", default="x", help="Platform site key (default x)")
    parser.add_argument("--dry-run", "-n", action="store_true")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    task = _parse_task(args.task)
    if args.medium:
        task["medium"] = args.medium.strip().lower()
    task.setdefault("content_root", str(content_root_from_env()))

    if dry_run_requested([]) or args.dry_run:
        write_ok({"dry_run": True, "op": args.op, "task": task, "site": args.site})
        return 0

    content_root = content_root_from_env()
    try:
        workspace_cfg, _layout = load_workspace(start_dir=content_root)
        cfg: dict[str, Any] = {
            "skills": {"social_media_manager": {}},
            "tools": {},
        }
        if workspace_cfg is not None:
            raw_tools = getattr(workspace_cfg, "tools", None)
            if isinstance(raw_tools, dict):
                cfg["tools"] = raw_tools
            skills = getattr(workspace_cfg, "skills", None)
            if isinstance(skills, dict):
                cfg["skills"] = skills
            # Also expose integrations-style enabled from SMM twexapi block.
            smm = skills.get("social_media_manager") if isinstance(skills, dict) else None
            if isinstance(smm, dict):
                tw = smm.get("twexapi")
                if isinstance(tw, dict):
                    cfg["integrations"] = {"twexapi": {"enabled": bool(tw.get("enabled"))}}
        fn = getattr(x_ops, args.op)
        result = asyncio.run(fn(task=task, cfg=cfg, site=args.site))
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        write_error(code="X_OPS_ERROR", error=str(exc))
        return 1
    if not isinstance(result, dict) or not result.get("ok", False):
        write_error(
            code=str((result or {}).get("code") or "X_OPS_FAILED"),
            error=str((result or {}).get("error") or result),
        )
        return 1
    write_ok(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
