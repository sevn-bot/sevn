"""Unified X/Twitter ops facade over ``browser`` | ``twexapi`` (DB6-DB10).

Thin public wrappers over :func:`sevn.integrations.social_media.x_ops_dispatch.run_op`.
TwexAPI body/path packing lives in ``x_ops_pack``; OpSpec rows wire them in ``x_ops_dispatch``.

Module: sevn.integrations.social_media.x_ops
Depends: sevn.integrations.social_media.x_ops_dispatch
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sevn.integrations.social_media.x_ops_dispatch import (
    FACADE_OPS,
    cookie_bridge_log_safe,
    cookies_for_twexapi,
    run_op,
)

__all__ = [
    "FACADE_OPS",
    "advanced_search_page",
    "bookmark",
    "cookie_bridge_log_safe",
    "cookies_for_twexapi",
    "create_quote_tweet",
    "create_tweet_or_reply",
    "create_tweet_thread",
    "delete_bookmark",
    "delete_retweet",
    "delete_tweets",
    "fetch_article_markdown",
    "follow_user",
    "get_users_by_usernames",
    "home_timeline_collect",
    "like_tweet",
    "post_tweet_auto_cookie",
    "retweet",
    "search_hashtags",
    "session_status",
    "unlike_tweet",
]

_FacadeFn = Callable[
    [dict[str, Any] | None, dict[str, Any] | None, str],
    Awaitable[dict[str, Any]],
]


def _wrap(op: str) -> _FacadeFn:
    """Build a thin public facade callable for ``op``.

    Args:
        op (str): Facade op name in :data:`FACADE_OPS`.

    Returns:
        _FacadeFn: ``async (task, cfg, site) -> envelope``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_wrap("like_tweet"))
        True
    """

    async def _fn(
        task: dict[str, Any] | None = None,
        cfg: dict[str, Any] | None = None,
        site: str = "x",
    ) -> dict[str, Any]:
        return await run_op(op, task, cfg, site)

    _fn.__name__ = op
    _fn.__qualname__ = op
    _fn.__doc__ = f"Facade op ``{op}`` — see ``x_ops_dispatch.run_op`` / §4 catalog."
    return _fn


advanced_search_page = _wrap("advanced_search_page")
search_hashtags = _wrap("search_hashtags")
like_tweet = _wrap("like_tweet")
unlike_tweet = _wrap("unlike_tweet")
retweet = _wrap("retweet")
delete_retweet = _wrap("delete_retweet")
bookmark = _wrap("bookmark")
delete_bookmark = _wrap("delete_bookmark")
create_tweet_or_reply = _wrap("create_tweet_or_reply")
create_quote_tweet = _wrap("create_quote_tweet")
create_tweet_thread = _wrap("create_tweet_thread")
delete_tweets = _wrap("delete_tweets")
post_tweet_auto_cookie = _wrap("post_tweet_auto_cookie")
get_users_by_usernames = _wrap("get_users_by_usernames")
follow_user = _wrap("follow_user")
fetch_article_markdown = _wrap("fetch_article_markdown")
home_timeline_collect = _wrap("home_timeline_collect")
session_status = _wrap("session_status")
