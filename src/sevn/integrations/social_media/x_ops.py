"""Unified X/Twitter ops facade over ``browser`` | ``twexapi`` (DB6-DB10).

Module: sevn.integrations.social_media.x_ops
Depends: sevn.integrations.social_media.x_ops_dispatch,
    sevn.integrations.social_media.medium, sevn.integrations.social_media.readiness,
    sevn.integrations.twexapi.config

Exports:
    advanced_search_page — §4 paged advanced search.
    search_hashtags — §4 hashtag search.
    like_tweet — like a tweet.
    unlike_tweet — unlike a tweet.
    retweet — retweet a tweet.
    delete_retweet — undo a retweet.
    bookmark — bookmark a tweet.
    delete_bookmark — remove a bookmark.
    create_tweet_or_reply — create a tweet or reply.
    create_quote_tweet — create a quote tweet.
    create_tweet_thread — create a tweet thread.
    delete_tweets — delete one or more tweets.
    post_tweet_auto_cookie — TwexAPI pool-cookie post (browser coerces to create).
    get_users_by_usernames — look up users by username.
    follow_user — follow a user.
    fetch_article_markdown — fetch an X article as markdown.
    home_timeline_collect — structured home/timeline (reuses W3 browser collect).
    session_status — CDP / profile / login / TwexAPI key presence (DB10).
"""

from __future__ import annotations

import os
from typing import Any

from sevn.integrations.social_media.medium import resolve_social_medium
from sevn.integrations.social_media.readiness import (
    build_social_media_readiness_sync,
    twexapi_key_configured,
)
from sevn.integrations.social_media.x_ops_dispatch import (
    cookie_bridge_log_safe,
    cookies_for_twexapi,
    run_op,
)
from sevn.integrations.social_media.x_ops_dispatch import (
    envelope as _envelope,
)
from sevn.integrations.social_media.x_ops_dispatch import (
    resolve_content_root as _resolve_content_root,
)
from sevn.integrations.social_media.x_ops_dispatch import (
    smm_cfg as _smm_cfg,
)
from sevn.integrations.social_media.x_ops_dispatch import (
    thread_items as _thread_items,
)
from sevn.integrations.twexapi.config import (
    TWEXAPI_ENV_KEYS,
    load_twexapi_settings,
)

__all__ = [
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


async def advanced_search_page(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Paged advanced X search (browser collect or TwexAPI ``search_page``).

    Args:
        task (dict[str, Any] | None): Task args (``query`` / ``searchTerms``, medium).
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(advanced_search_page)
        True
    """
    task = dict(task or {})
    body: dict[str, Any] = {}
    if "searchTerms" in task:
        body["searchTerms"] = task["searchTerms"]
    elif task.get("query"):
        body["searchTerms"] = [str(task["query"])]
    for key in ("sortBy", "next_cursor"):
        if task.get(key):
            body[key] = task[key]
    return await run_op("advanced_search_page", task, cfg, site, twexapi_body=body or None)


async def search_hashtags(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Search X hashtags via TwexAPI ``hashtags`` or browser ``#tag`` search.

    Args:
        task (dict[str, Any] | None): Task args (``hashtags`` / ``query``).
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(search_hashtags)
        True
    """
    task = dict(task or {})
    tags = task.get("hashtags")
    if isinstance(tags, str):
        tags = [tags]
    if not tags and task.get("query"):
        tags = [str(task["query"])]
    return await run_op(
        "search_hashtags", task, cfg, site, twexapi_body={"hashtags": list(tags or [])}
    )


async def _tweet_id_write(
    op: str,
    task: dict[str, Any] | None,
    cfg: dict[str, Any] | None,
    site: str,
) -> dict[str, Any]:
    """Dispatch a tweet-id path-param write op.

    Args:
        op (str): Facade op name.
        task (dict[str, Any] | None): Task with ``tweet_id``.
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_tweet_id_write)
        True
    """
    task = dict(task or {})
    tweet_id = str(task.get("tweet_id") or "").strip()
    return await run_op(
        op,
        task,
        cfg,
        site,
        twexapi_path_params={"tweet_id": tweet_id or "0"},
        twexapi_body={},
    )


async def like_tweet(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Like a tweet (TwexAPI; browser → ``BROWSER_OP_UNSUPPORTED``).

    Args:
        task (dict[str, Any] | None): Must include ``tweet_id`` (and cookie on twexapi).
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(like_tweet)
        True
    """
    return await _tweet_id_write("like_tweet", task, cfg, site)


async def unlike_tweet(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Unlike a tweet.

    Args:
        task (dict[str, Any] | None): Task with ``tweet_id``.
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(unlike_tweet)
        True
    """
    return await _tweet_id_write("unlike_tweet", task, cfg, site)


async def retweet(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Retweet a tweet.

    Args:
        task (dict[str, Any] | None): Task with ``tweet_id``.
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(retweet)
        True
    """
    return await _tweet_id_write("retweet", task, cfg, site)


async def delete_retweet(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Undo a retweet.

    Args:
        task (dict[str, Any] | None): Task with ``tweet_id``.
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(delete_retweet)
        True
    """
    return await _tweet_id_write("delete_retweet", task, cfg, site)


async def bookmark(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Bookmark a tweet.

    Args:
        task (dict[str, Any] | None): Task with ``tweet_id``.
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(bookmark)
        True
    """
    return await _tweet_id_write("bookmark", task, cfg, site)


async def delete_bookmark(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Remove a bookmark.

    Args:
        task (dict[str, Any] | None): Task with ``tweet_id``.
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(delete_bookmark)
        True
    """
    return await _tweet_id_write("delete_bookmark", task, cfg, site)


async def create_tweet_or_reply(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Create a tweet or reply (composer / TwexAPI create).

    Args:
        task (dict[str, Any] | None): Task with ``text`` / ``tweet_content``.
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(create_tweet_or_reply)
        True
    """
    task = dict(task or {})
    text = str(task.get("text") or task.get("tweet_content") or "")
    body: dict[str, Any] = {"tweet_content": text}
    for key in ("reply_tweet_id", "media_url"):
        if task.get(key):
            body[key] = task[key]
    return await run_op("create_tweet_or_reply", task, cfg, site, twexapi_body=body)


async def create_quote_tweet(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Create a quote tweet (TwexAPI only; browser → ``BROWSER_OP_UNSUPPORTED``).

    Args:
        task (dict[str, Any] | None): Task with ``text`` and quote target id/url.
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(create_quote_tweet)
        True
    """
    task = dict(task or {})
    text = str(task.get("text") or task.get("tweet_content") or "")
    body: dict[str, Any] = {"tweet_content": text}
    for key in ("tweet_id", "quoted_tweet_id", "media_url"):
        if task.get(key):
            body[key] = task[key]
    return await run_op("create_quote_tweet", task, cfg, site, twexapi_body=body)


async def create_tweet_thread(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Create a tweet thread; browser maps to ``post`` when ``items``/``texts`` present.

    Args:
        task (dict[str, Any] | None): Task with ``items`` (list[str]) or ``texts``.
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(create_tweet_thread)
        True
    """
    task = dict(task or {})
    items = _thread_items(task)
    return await run_op("create_tweet_thread", task, cfg, site, twexapi_body={"items": list(items)})


async def delete_tweets(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Delete one or more tweets (TwexAPI; browser → ``BROWSER_OP_UNSUPPORTED``).

    Args:
        task (dict[str, Any] | None): Task with tweet id(s) / username.
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(delete_tweets)
        True
    """
    task = dict(task or {})
    body = {k: task[k] for k in ("username", "target_id", "tweet_ids") if k in task}
    return await run_op("delete_tweets", task, cfg, site, twexapi_body=body)


async def post_tweet_auto_cookie(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Post via TwexAPI pool cookie; browser coerces to ``create_tweet_or_reply``.

    Args:
        task (dict[str, Any] | None): Task with ``text`` / ``tweet_content``.
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(post_tweet_auto_cookie)
        True
    """
    task = dict(task or {})
    text = str(task.get("text") or task.get("tweet_content") or "")
    return await run_op(
        "post_tweet_auto_cookie",
        task,
        cfg,
        site,
        twexapi_body={"tweet_content": text},
    )


async def get_users_by_usernames(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Look up users by username (TwexAPI ``users`` or browser profile reads).

    Args:
        task (dict[str, Any] | None): Task with ``usernames`` list or ``query``.
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(get_users_by_usernames)
        True
    """
    task = dict(task or {})
    names = task.get("usernames")
    if isinstance(names, str):
        names = [n.strip() for n in names.split(",") if n.strip()]
    if not names and task.get("query"):
        names = [str(task["query"]).lstrip("@")]
    return await run_op("get_users_by_usernames", task, cfg, site, twexapi_body=list(names or []))


async def follow_user(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Follow a user (write-gated; browser → ``BROWSER_OP_UNSUPPORTED``).

    Args:
        task (dict[str, Any] | None): Task with ``username``.
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(follow_user)
        True
    """
    task = dict(task or {})
    username = str(task.get("username") or task.get("query") or "").lstrip("@")
    return await run_op("follow_user", task, cfg, site, twexapi_body={"username": username})


async def fetch_article_markdown(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Fetch an X article as markdown (TwexAPI) or browser extract plan.

    Args:
        task (dict[str, Any] | None): Task with ``tweet_id``.
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(fetch_article_markdown)
        True
    """
    task = dict(task or {})
    tweet_id = str(task.get("tweet_id") or "").strip()
    return await run_op(
        "fetch_article_markdown",
        task,
        cfg,
        site,
        twexapi_path_params={"tweet_id": tweet_id or "0"},
    )


async def home_timeline_collect(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Collect structured home/timeline posts (browser ``home_feed``; TwexAPI timeline).

    Args:
        task (dict[str, Any] | None): Optional ``screen_name`` for TwexAPI substitute.
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(home_timeline_collect)
        True
    """
    task = dict(task or {})
    screen = str(task.get("screen_name") or task.get("username") or "home").lstrip("@")
    return await run_op(
        "home_timeline_collect",
        task,
        cfg,
        site,
        twexapi_path_params={"screen_name": screen},
        twexapi_body={},
    )


async def session_status(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Report CDP reachability, profile, login probe, and TwexAPI key presence (DB10).

    Args:
        task (dict[str, Any] | None): Optional ``content_root``.
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key for login probe.

    Returns:
        dict[str, Any]: Normalized envelope with readiness fields under ``data``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(session_status)
        True
    """
    task = dict(task or {})
    cfg = dict(cfg or {})
    medium = resolve_social_medium(task, _smm_cfg(cfg), site)
    content_root = _resolve_content_root(task)
    try:
        snap = build_social_media_readiness_sync(content_root, site=site)
    except (OSError, ValueError, RuntimeError) as exc:
        return _envelope(
            ok=False,
            medium=medium,
            op="session_status",
            data={},
            error=str(exc),
            code="STATUS_ERROR",
        )
    raw_browser = snap.get("browser")
    browser: dict[str, Any] = raw_browser if isinstance(raw_browser, dict) else {}
    raw_twex = snap.get("twexapi")
    twex: dict[str, Any] = raw_twex if isinstance(raw_twex, dict) else {}
    settings, _ = load_twexapi_settings(content_root)
    key_present = twexapi_key_configured(settings) or any(
        os.environ.get(name, "").strip() for name in ("SEVN_SECRET_TWEXAPI", *TWEXAPI_ENV_KEYS)
    )
    data = {
        "cdp_reachable": bool(browser.get("cdp_reachable")),
        "cdp_ok": bool(browser.get("cdp_reachable")),
        "reachability": "ok" if browser.get("cdp_reachable") else "down",
        "profile_path": browser.get("profile_dir"),
        "profile_dir": browser.get("profile_dir"),
        "profile_exists": bool(browser.get("profile_exists")),
        "login": snap.get("site"),
        "twexapi_key_present": bool(key_present),
        "key_present": bool(key_present),
        "twexapi_enabled": bool(twex.get("enabled")),
    }
    return _envelope(ok=True, medium=medium, op="session_status", data=data)
