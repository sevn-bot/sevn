"""Browser tool plan shaping for X ops facade dispatch.

Module: sevn.integrations.social_media.x_ops_browser_plan
Depends: sevn.integrations.social_media.x_ops_guardrails,
    sevn.integrations.social_media.x_ops_pack

Exports:
    browser_plan — build a CDP ``browser`` tool plan for the parent turn.
"""

from __future__ import annotations

from typing import Any

from sevn.integrations.social_media.x_ops_guardrails import DISCOVERY_OPS
from sevn.integrations.social_media.x_ops_pack import thread_items

__all__ = ["browser_plan"]


def browser_plan(op: str, task: dict[str, Any], site: str, social_op: str) -> dict[str, Any]:
    """Build a CDP ``browser`` tool plan for the parent turn.

    Args:
        op (str): Facade op name.
        task (dict[str, Any]): Task args.
        site (str): Site key.
        social_op (str): Mapped ``SocialRecipe`` op.

    Returns:
        dict[str, Any]: Plan payload for ``action=social``.

    Examples:
        >>> browser_plan("home_timeline_collect", {}, "x", "home_feed")["action"]
        'social'
    """
    query = task.get("query") or task.get("text") or ""
    if op == "search_hashtags":
        tags = task.get("hashtags") or task.get("query") or ""
        if isinstance(tags, list):
            query = " ".join(f"#{str(t).lstrip('#')}" for t in tags)
        else:
            query = f"#{str(tags).lstrip('#')}" if tags else ""
    if op == "discover_followers":
        username = str(
            task.get("username") or task.get("screen_name") or task.get("query") or ""
        ).lstrip("@")
        query = f"followers:{username}" if username else query
    if op == "discover_mutual_graph":
        names = task.get("usernames")
        if isinstance(names, list):
            handles = [str(n).strip().lstrip("@") for n in names if str(n).strip()]
            if len(handles) >= 2:
                query = f"mutual followers {' '.join(handles[:2])}"
        elif task.get("query"):
            query = f"mutual followers {task['query']}"
    body = task.get("text") or task.get("tweet_content") or ""
    tweet_id = str(task.get("tweet_id") or "")
    url = task.get("url") or task.get("tweet_url") or ""
    if op == "comment_on_tweet" and tweet_id and not url:
        url = f"https://x.com/i/status/{tweet_id}"
    if (
        tweet_id
        and not url
        and op
        in (
            "collect_tweet_replies",
            "get_tweet_stats",
            "get_new_comments_on_tweet",
        )
    ):
        url = f"https://x.com/i/status/{tweet_id}"
    plan: dict[str, Any] = {
        "action": "social",
        "site": site,
        "op": social_op,
        "facade_op": op,
        "query": query,
        "url": url,
        "body": body,
        "tweet_id": tweet_id,
        "username": task.get("username") or "",
        "hint": (
            f"Invoke browser tool action=social site={site} for facade op={op} "
            f"(mapped social op={social_op}). Write ops need "
            f"tools.browser.social.{site}.allow_write=true."
        ),
    }
    if op == "create_tweet_thread":
        items = thread_items(task)
        plan["items"] = items
        plan["texts"] = items
        if items and not body:
            plan["body"] = items[0]
    if op == "get_new_comments_on_tweet":
        for key in ("since_id", "since_cursor", "last_seen_id", "last_seen_at"):
            if task.get(key) is not None:
                plan[key] = task[key]
    if op in DISCOVERY_OPS:
        plan["discovery"] = True
        for key in ("max_items", "next_cursor", "cursor", "usernames"):
            if task.get(key) is not None:
                plan[key] = task[key]
    return plan
