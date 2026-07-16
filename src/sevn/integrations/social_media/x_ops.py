"""Unified X/Twitter ops facade over ``browser`` | ``twexapi`` (DB6-DB10).

Module: sevn.integrations.social_media.x_ops
Depends: sevn.integrations.social_media.medium, sevn.integrations.twexapi.client,
    sevn.integrations.social_media.readiness

Exports:
    cookies_for_twexapi — map browser export_cookies payload → TwexAPI cookie field.
    cookie_bridge_log_safe — log-safe summary of a cookie export (no secret values).
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
from pathlib import Path
from typing import Any

from sevn.integrations.social_media.medium import resolve_social_medium
from sevn.integrations.social_media.readiness import (
    build_social_media_readiness_sync,
    twexapi_key_configured,
)
from sevn.integrations.twexapi.client import (
    TWEXAPI_WRITE_OPS,
    TwexApiClient,
    TwexApiError,
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

# Browser write ops gated by tools.browser.social.x.allow_write (DB8).
_BROWSER_WRITE_OPS: frozenset[str] = frozenset(
    {
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
        "follow_user",
        "post_tweet_auto_cookie",
    }
)

# Map facade op → TwexAPI allowlist key (when names differ).
_TWEXAPI_OP_ALIASES: dict[str, str] = {
    "advanced_search_page": "search_page",
    "search_hashtags": "hashtags",
    "get_users_by_usernames": "users",
    "home_timeline_collect": "timeline_page",
}


def cookies_for_twexapi(export_payload: dict[str, Any]) -> str:
    """Map a browser ``export_cookies``-shaped payload to a TwexAPI cookie string.

    Prefers an explicit ``cookie_header``; otherwise builds ``name=value`` pairs
    from a ``cookies`` list. Never logs values (convention 13).

    Args:
        export_payload (dict[str, Any]): Export dict with ``cookie_header`` and/or
            ``cookies`` list of ``{name, value}`` objects.

    Returns:
        str: Cookie header suitable for TwexAPI write bodies.

    Examples:
        >>> cookies_for_twexapi({"cookie_header": "a=1; b=2"})
        'a=1; b=2'
    """
    header = export_payload.get("cookie_header")
    if isinstance(header, str) and header.strip():
        return header.strip()
    cookies = export_payload.get("cookies")
    if isinstance(cookies, list):
        parts: list[str] = []
        for item in cookies:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            value = item.get("value")
            if isinstance(name, str) and name.strip() and isinstance(value, str):
                parts.append(f"{name.strip()}={value}")
        if parts:
            return "; ".join(parts)
    return ""


def cookie_bridge_log_safe(export_payload: dict[str, Any]) -> dict[str, Any]:
    """Return a log-safe summary of a cookie export (no secret values).

    Args:
        export_payload (dict[str, Any]): Raw export payload (may contain secrets).

    Returns:
        dict[str, Any]: Counts and cookie *names* only.

    Examples:
        >>> cookie_bridge_log_safe({"cookies": [{"name": "ct0", "value": "secret"}]})["names"]
        ['ct0']
    """
    cookies = export_payload.get("cookies")
    names: list[str] = []
    if isinstance(cookies, list):
        for item in cookies:
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    names.append(name.strip())
    has_header = bool(
        isinstance(export_payload.get("cookie_header"), str)
        and str(export_payload.get("cookie_header")).strip()
    )
    return {
        "cookie_count": len(names),
        "names": names,
        "has_cookie_header": has_header,
        "mapped_nonempty": bool(cookies_for_twexapi(export_payload)),
    }


def _envelope(
    *,
    ok: bool,
    medium: str,
    op: str,
    data: Any = None,
    error: str | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    """Build the normalized X-ops response envelope.

    Args:
        ok (bool): Success flag.
        medium (str): ``browser`` or ``twexapi``.
        op (str): Facade op name.
        data (Any): Result payload.
        error (str | None): Human-readable error when ``ok`` is false.
        code (str | None): Machine-readable error code.

    Returns:
        dict[str, Any]: Envelope with ``ok``, ``medium``, ``op``, ``data``.

    Examples:
        >>> _envelope(ok=True, medium="browser", op="session_status", data={})["ok"]
        True
    """
    out: dict[str, Any] = {
        "ok": ok,
        "medium": medium,
        "op": op,
        "data": {} if data is None else data,
    }
    if error is not None:
        out["error"] = error
    if code is not None:
        out["code"] = code
    return out


def _smm_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    """Extract the ``skills.social_media_manager`` block when present.

    Args:
        cfg (dict[str, Any]): Full workspace cfg, SMM block, or test stub.

    Returns:
        dict[str, Any]: Medium-resolution config mapping.

    Examples:
        >>> _smm_cfg({"default_medium": "browser"})["default_medium"]
        'browser'
    """
    skills = cfg.get("skills")
    if isinstance(skills, dict):
        block = skills.get("social_media_manager")
        if isinstance(block, dict):
            return block
    return cfg


def _browser_allow_write(cfg: dict[str, Any], site: str = "x") -> bool:
    """Return whether browser write ops are enabled for ``site`` (DB8).

    Args:
        cfg (dict[str, Any]): Config tree that may contain ``tools.browser``.
        site (str): Social site key.

    Returns:
        bool: ``True`` only when ``tools.browser.social.<site>.allow_write`` is true.

    Examples:
        >>> _browser_allow_write({"tools": {"browser": {"social": {"x": {"allow_write": True}}}}})
        True
    """
    tools = cfg.get("tools")
    if not isinstance(tools, dict):
        return False
    browser = tools.get("browser")
    if not isinstance(browser, dict):
        return False
    social = browser.get("social")
    if not isinstance(social, dict):
        return False
    section = social.get(site)
    return bool(isinstance(section, dict) and section.get("allow_write") is True)


def _twexapi_enabled(cfg: dict[str, Any]) -> bool:
    """Return whether TwexAPI medium writes/calls are enabled (DB8).

    Checks ``integrations.twexapi.enabled``, then
    ``skills.social_media_manager.twexapi.enabled``, then a bare ``twexapi`` block.

    Args:
        cfg (dict[str, Any]): Config tree or test stub.

    Returns:
        bool: Enabled flag (default ``False``).

    Examples:
        >>> _twexapi_enabled({"integrations": {"twexapi": {"enabled": False}}})
        False
    """
    integ = cfg.get("integrations")
    if isinstance(integ, dict):
        tw = integ.get("twexapi")
        if isinstance(tw, dict) and "enabled" in tw:
            return bool(tw["enabled"])
    smm = _smm_cfg(cfg)
    tw = smm.get("twexapi")
    if isinstance(tw, dict) and "enabled" in tw:
        return bool(tw["enabled"])
    tw2 = cfg.get("twexapi")
    if isinstance(tw2, dict) and "enabled" in tw2:
        return bool(tw2["enabled"])
    return False


def _task_cookie(task: dict[str, Any]) -> str | None:
    """Extract a TwexAPI cookie from the task without logging it.

    Args:
        task (dict[str, Any]): Task payload.

    Returns:
        str | None: Cookie string or ``None``.

    Examples:
        >>> _task_cookie({"cookie": "ct0=x"}) == "ct0=x"
        True
    """
    raw = task.get("cookie")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    export = task.get("export_cookies")
    if isinstance(export, dict):
        mapped = cookies_for_twexapi(export)
        return mapped or None
    return None


def _task_proxy(task: dict[str, Any]) -> str | None:
    """Extract an optional proxy URL from the task.

    Args:
        task (dict[str, Any]): Task payload.

    Returns:
        str | None: Proxy URL or ``None``.

    Examples:
        >>> _task_proxy({}) is None
        True
    """
    raw = task.get("proxy")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _resolve_content_root(task: dict[str, Any]) -> Path:
    """Resolve workspace content root from the task or cwd.

    Args:
        task (dict[str, Any]): Task payload (optional ``content_root``).

    Returns:
        Path: Absolute content root.

    Examples:
        >>> _resolve_content_root({}).is_absolute()
        True
    """
    content_root_raw = task.get("content_root")
    if content_root_raw:
        return Path(str(content_root_raw)).expanduser().resolve()
    return Path.cwd()


def _browser_plan(op: str, task: dict[str, Any], site: str) -> dict[str, Any]:
    """Build a CDP ``browser`` tool plan for the parent turn.

    Args:
        op (str): Facade op name.
        task (dict[str, Any]): Task args.
        site (str): Site key.

    Returns:
        dict[str, Any]: Plan payload for ``action=social`` (or documented exception).

    Examples:
        >>> _browser_plan("home_timeline_collect", {}, "x")["action"]
        'social'
    """
    social_op = {
        "home_timeline_collect": "home_feed",
        "advanced_search_page": "search",
        "search_hashtags": "search",
        "create_tweet_or_reply": "post",
        "create_quote_tweet": "post",
        "create_tweet_thread": "post",
        "post_tweet_auto_cookie": "post",
        "get_users_by_usernames": "read",
        "fetch_article_markdown": "read",
    }.get(op, op)
    query = task.get("query") or task.get("text") or ""
    if op == "search_hashtags":
        tags = task.get("hashtags") or task.get("query") or ""
        if isinstance(tags, list):
            query = " ".join(f"#{str(t).lstrip('#')}" for t in tags)
        else:
            query = f"#{str(tags).lstrip('#')}" if tags else ""
    return {
        "action": "social",
        "site": site,
        "op": social_op,
        "facade_op": op,
        "query": query,
        "url": task.get("url") or task.get("tweet_url") or "",
        "body": task.get("text") or task.get("tweet_content") or "",
        "tweet_id": task.get("tweet_id") or "",
        "username": task.get("username") or "",
        "hint": (
            f"Invoke browser tool action=social site={site} for facade op={op} "
            f"(mapped social op={social_op}). Write ops need "
            f"tools.browser.social.{site}.allow_write=true."
        ),
    }


async def _dispatch(
    op: str,
    task: dict[str, Any],
    cfg: dict[str, Any],
    site: str,
    *,
    is_write: bool = False,
    twexapi_body: dict[str, Any] | list[Any] | None = None,
    twexapi_path_params: dict[str, str] | None = None,
    twexapi_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve medium, apply gates, and dispatch to browser plan or TwexAPI.

    Args:
        op (str): Facade op name.
        task (dict[str, Any]): Task payload.
        cfg (dict[str, Any]): Config / test stub.
        site (str): Platform site key.
        is_write (bool): When true, apply DB8 write gates.
        twexapi_body (dict[str, Any] | list[Any] | None): TwexAPI JSON body.
        twexapi_path_params (dict[str, str] | None): Path params.
        twexapi_params (dict[str, Any] | None): Query params.

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_dispatch)
        True
    """
    medium = resolve_social_medium(task, _smm_cfg(cfg), site)

    # post_tweet_auto_cookie: TwexAPI pool cookie ≠ browser profile cookie (DB9).
    if op == "post_tweet_auto_cookie" and medium == "browser":
        coerced = await _dispatch(
            "create_tweet_or_reply",
            {**task, "medium": "browser"},
            cfg,
            site,
            is_write=True,
        )
        coerced["op"] = "post_tweet_auto_cookie"
        data = dict(coerced.get("data") or {})
        data["coerced_from"] = "post_tweet_auto_cookie"
        data["note"] = (
            "post_tweet_auto_cookie uses TwexAPI's pool cookie on medium=twexapi; "
            "browser medium coerces to create_tweet_or_reply with the CDP profile session."
        )
        coerced["data"] = data
        if coerced.get("ok"):
            coerced["code"] = "COERCED_BROWSER_CREATE"
        return coerced

    if is_write and medium == "browser" and not _browser_allow_write(cfg, site):
        return _envelope(
            ok=False,
            medium=medium,
            op=op,
            data={},
            error=f"browser write disabled — set tools.browser.social.{site}.allow_write=true",
            code="WRITE_DISABLED",
        )

    if medium == "twexapi":
        if not _twexapi_enabled(cfg):
            return _envelope(
                ok=False,
                medium=medium,
                op=op,
                data={},
                error="TwexAPI medium disabled",
                code="TWEXAPI_DISABLED",
            )

        twex_key = _TWEXAPI_OP_ALIASES.get(op, op)
        content_root = _resolve_content_root(task)
        try:
            settings, _ = load_twexapi_settings(content_root)
            api_key = ""
            for env_name in ("SEVN_SECRET_TWEXAPI", *TWEXAPI_ENV_KEYS):
                val = os.environ.get(env_name, "").strip()
                if val:
                    api_key = val
                    break
            if not api_key:
                api_key = "missing-twexapi-key"
            client = TwexApiClient(api_key, base_url=settings.base_url)
            body = twexapi_body
            path_params = twexapi_path_params
            params = twexapi_params
            write_via_helper = is_write and twex_key in TWEXAPI_WRITE_OPS
            if write_via_helper:
                cookie = _task_cookie(task)
                proxy = _task_proxy(task)
                if not cookie:
                    return _envelope(
                        ok=False,
                        medium=medium,
                        op=op,
                        data={},
                        error="TwexAPI write op requires cookie (or export_cookies bridge)",
                        code="COOKIE_REQUIRED",
                    )
                data = await client.call_write_op(
                    twex_key,
                    params=params,
                    body=body if isinstance(body, dict) else None,
                    path_params=path_params,
                    cookie=cookie,
                    proxy=proxy,
                )
            else:
                data = await client.call_op(
                    twex_key,
                    params=params,
                    body=body,
                    path_params=path_params,
                )
            return _envelope(ok=True, medium=medium, op=op, data=data)
        except TwexApiError as exc:
            return _envelope(
                ok=False,
                medium=medium,
                op=op,
                data={},
                error=str(exc),
                code="TWEXAPI_ERROR",
            )
        except (OSError, ValueError, RuntimeError) as exc:
            return _envelope(
                ok=False,
                medium=medium,
                op=op,
                data={},
                error=str(exc),
                code="TWEXAPI_ERROR",
            )

    # browser medium
    plan = _browser_plan(op, task, site)
    return _envelope(ok=True, medium="browser", op=op, data={"browser_plan": plan})


# --- public facade ops -------------------------------------------------------


async def advanced_search_page(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Paged advanced X search (browser scroll collect or TwexAPI ``search_page``).

    Args:
        task (dict[str, Any] | None): Task args (``query`` / ``searchTerms``, medium).
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key (TwexAPI coerces non-x to browser).

    Returns:
        dict[str, Any]: Normalized envelope.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(advanced_search_page)
        True
    """
    task = dict(task or {})
    cfg = dict(cfg or {})
    body: dict[str, Any] = {}
    if "searchTerms" in task:
        body["searchTerms"] = task["searchTerms"]
    elif task.get("query"):
        body["searchTerms"] = [str(task["query"])]
    if task.get("sortBy"):
        body["sortBy"] = task["sortBy"]
    if task.get("next_cursor"):
        body["next_cursor"] = task["next_cursor"]
    return await _dispatch(
        "advanced_search_page",
        task,
        cfg,
        site,
        twexapi_body=body or None,
    )


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
    cfg = dict(cfg or {})
    tags = task.get("hashtags")
    if isinstance(tags, str):
        tags = [tags]
    if not tags and task.get("query"):
        tags = [str(task["query"])]
    body: dict[str, Any] = {"hashtags": list(tags or [])}
    return await _dispatch(
        "search_hashtags",
        task,
        cfg,
        site,
        twexapi_body=body,
    )


async def like_tweet(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Like a tweet (browser CDP plan or TwexAPI write).

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
    task = dict(task or {})
    cfg = dict(cfg or {})
    tweet_id = str(task.get("tweet_id") or "").strip()
    return await _dispatch(
        "like_tweet",
        task,
        cfg,
        site,
        is_write=True,
        twexapi_path_params={"tweet_id": tweet_id or "0"},
        twexapi_body={},
    )


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
    task = dict(task or {})
    cfg = dict(cfg or {})
    tweet_id = str(task.get("tweet_id") or "").strip()
    return await _dispatch(
        "unlike_tweet",
        task,
        cfg,
        site,
        is_write=True,
        twexapi_path_params={"tweet_id": tweet_id or "0"},
        twexapi_body={},
    )


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
    task = dict(task or {})
    cfg = dict(cfg or {})
    tweet_id = str(task.get("tweet_id") or "").strip()
    return await _dispatch(
        "retweet",
        task,
        cfg,
        site,
        is_write=True,
        twexapi_path_params={"tweet_id": tweet_id or "0"},
        twexapi_body={},
    )


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
    task = dict(task or {})
    cfg = dict(cfg or {})
    tweet_id = str(task.get("tweet_id") or "").strip()
    return await _dispatch(
        "delete_retweet",
        task,
        cfg,
        site,
        is_write=True,
        twexapi_path_params={"tweet_id": tweet_id or "0"},
        twexapi_body={},
    )


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
    task = dict(task or {})
    cfg = dict(cfg or {})
    tweet_id = str(task.get("tweet_id") or "").strip()
    return await _dispatch(
        "bookmark",
        task,
        cfg,
        site,
        is_write=True,
        twexapi_path_params={"tweet_id": tweet_id or "0"},
        twexapi_body={},
    )


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
    task = dict(task or {})
    cfg = dict(cfg or {})
    tweet_id = str(task.get("tweet_id") or "").strip()
    return await _dispatch(
        "delete_bookmark",
        task,
        cfg,
        site,
        is_write=True,
        twexapi_path_params={"tweet_id": tweet_id or "0"},
        twexapi_body={},
    )


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
    cfg = dict(cfg or {})
    text = str(task.get("text") or task.get("tweet_content") or "")
    body: dict[str, Any] = {"tweet_content": text}
    if task.get("reply_tweet_id"):
        body["reply_tweet_id"] = task["reply_tweet_id"]
    if task.get("media_url"):
        body["media_url"] = task["media_url"]
    return await _dispatch(
        "create_tweet_or_reply",
        task,
        cfg,
        site,
        is_write=True,
        twexapi_body=body,
    )


async def create_quote_tweet(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Create a quote tweet.

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
    cfg = dict(cfg or {})
    text = str(task.get("text") or task.get("tweet_content") or "")
    body: dict[str, Any] = {"tweet_content": text}
    for key in ("tweet_id", "quoted_tweet_id", "media_url"):
        if task.get(key):
            body[key] = task[key]
    return await _dispatch(
        "create_quote_tweet",
        task,
        cfg,
        site,
        is_write=True,
        twexapi_body=body,
    )


async def create_tweet_thread(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Create a tweet thread from an ordered list of texts.

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
    cfg = dict(cfg or {})
    items = task.get("items") or task.get("texts") or []
    if isinstance(items, str):
        items = [items]
    body: dict[str, Any] = {"items": list(items)}
    return await _dispatch(
        "create_tweet_thread",
        task,
        cfg,
        site,
        is_write=True,
        twexapi_body=body,
    )


async def delete_tweets(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Delete one or more tweets.

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
    cfg = dict(cfg or {})
    body: dict[str, Any] = {}
    for key in ("username", "target_id", "tweet_ids"):
        if key in task:
            body[key] = task[key]
    return await _dispatch(
        "delete_tweets",
        task,
        cfg,
        site,
        is_write=True,
        twexapi_body=body,
    )


async def post_tweet_auto_cookie(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Post via TwexAPI auto/pool cookie; browser coerces to ``create_tweet_or_reply``.

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
    cfg = dict(cfg or {})
    text = str(task.get("text") or task.get("tweet_content") or "")
    body: dict[str, Any] = {"tweet_content": text}
    return await _dispatch(
        "post_tweet_auto_cookie",
        task,
        cfg,
        site,
        is_write=True,
        twexapi_body=body,
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
    cfg = dict(cfg or {})
    names = task.get("usernames")
    if isinstance(names, str):
        names = [n.strip() for n in names.split(",") if n.strip()]
    if not names and task.get("query"):
        names = [str(task["query"]).lstrip("@")]
    body: list[Any] | dict[str, Any] = list(names or [])
    return await _dispatch(
        "get_users_by_usernames",
        task,
        cfg,
        site,
        twexapi_body=body,
    )


async def follow_user(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Follow a user (write-gated).

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
    cfg = dict(cfg or {})
    username = str(task.get("username") or task.get("query") or "").lstrip("@")
    body: dict[str, Any] = {"username": username}
    return await _dispatch(
        "follow_user",
        task,
        cfg,
        site,
        is_write=True,
        twexapi_body=body,
    )


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
    cfg = dict(cfg or {})
    tweet_id = str(task.get("tweet_id") or "").strip()
    return await _dispatch(
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
    cfg = dict(cfg or {})
    screen = str(task.get("screen_name") or task.get("username") or "home").lstrip("@")
    return await _dispatch(
        "home_timeline_collect",
        task,
        cfg,
        site,
        # TwexAPI has no /home; use timeline_page as documented substitute.
        twexapi_path_params={"screen_name": screen},
        twexapi_body={},
    )


async def session_status(
    task: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    site: str = "x",
) -> dict[str, Any]:
    """Report CDP reachability, profile, login probe, and TwexAPI key presence (DB10).

    Never returns secret values (convention 13).

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
        # Never include api_key / cookie / proxy values.
    }
    return _envelope(ok=True, medium=medium, op="session_status", data=data)
