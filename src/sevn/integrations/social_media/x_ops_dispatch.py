"""Internal OpSpec table and dispatch for the X ops facade.

Module: sevn.integrations.social_media.x_ops_dispatch
Depends: sevn.browser.recipes.social, sevn.integrations.social_media.medium,
    sevn.integrations.social_media.readiness, sevn.integrations.social_media.x_ops_pack,
    sevn.integrations.twexapi

Exports:
    cookies_for_twexapi — map browser export_cookies payload → TwexAPI cookie field.
    cookie_bridge_log_safe — log-safe summary of a cookie export (no secret values).
    envelope — build the normalized X-ops response envelope.
    resolve_content_root — resolve workspace content root from a task.
    run_op — normalize args and dispatch one facade op.
    smm_cfg — extract skills.social_media_manager block.

``FACADE_OPS`` (frozenset of §4 op names) and ``thread_items`` (re-export from
``x_ops_pack``) are also exported via ``__all__``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sevn.browser.recipes.social import social_write_allowed
from sevn.integrations.social_media.medium import resolve_social_medium
from sevn.integrations.social_media.readiness import (
    build_social_media_readiness_sync,
    twexapi_key_configured,
)
from sevn.integrations.social_media.x_ops_pack import (
    TwexBodyPacker,
    TwexPathPacker,
    pack_advanced_search_body,
    pack_auto_cookie_body,
    pack_comment_body,
    pack_create_body,
    pack_delete_body,
    pack_discover_followers_body,
    pack_discover_mutual_body,
    pack_discover_topic_body,
    pack_empty_body,
    pack_follow_body,
    pack_hashtags_body,
    pack_quote_body,
    pack_replies_body,
    pack_thread_body,
    pack_timeline_path,
    pack_tweet_detail_body,
    pack_tweet_id_path,
    pack_users_body,
    thread_items,
)
from sevn.integrations.twexapi.client import (
    TWEXAPI_WRITE_OPS,
    TwexApiClient,
    TwexApiError,
)
from sevn.integrations.twexapi.config import (
    TWEXAPI_ENV_KEYS,
    load_twexapi_settings,
    resolve_twexapi_api_key,
)

__all__ = [
    "EXPANSION_OPS",
    "FACADE_OPS",
    "W12_ENGAGEMENT_OPS",
    "W13_TIMELINE_OPS",
    "W14_DISCOVERY_OPS",
    "cookie_bridge_log_safe",
    "cookies_for_twexapi",
    "envelope",
    "resolve_content_root",
    "run_op",
    "smm_cfg",
    "thread_items",
]


@dataclass(frozen=True, slots=True)
class _OpSpec:
    """Table-driven metadata for one §4 facade op (sole capability table)."""

    name: str
    twex_key: str | None = None
    browser_social_op: str | None = None
    is_write: bool = False
    pack_body: TwexBodyPacker | None = None
    pack_path: TwexPathPacker | None = None

    @property
    def twexapi_op(self) -> str:
        """Return the TwexAPI allowlist key for this facade op.

        Returns:
            str: TwexAPI op name (alias or facade name).

        Examples:
            >>> _OpSpec("advanced_search_page", twex_key="search_page").twexapi_op
            'search_page'
        """
        return self.twex_key or self.name


_OP_SPECS: dict[str, _OpSpec] = {
    spec.name: spec
    for spec in (
        _OpSpec(
            "advanced_search_page",
            twex_key="search_page",
            browser_social_op="search",
            pack_body=pack_advanced_search_body,
        ),
        _OpSpec(
            "search_hashtags",
            twex_key="hashtags",
            browser_social_op="search",
            pack_body=pack_hashtags_body,
        ),
        _OpSpec(
            "like_tweet",
            is_write=True,
            pack_path=pack_tweet_id_path,
            pack_body=pack_empty_body,
        ),
        _OpSpec(
            "unlike_tweet",
            is_write=True,
            pack_path=pack_tweet_id_path,
            pack_body=pack_empty_body,
        ),
        _OpSpec(
            "retweet",
            is_write=True,
            pack_path=pack_tweet_id_path,
            pack_body=pack_empty_body,
        ),
        _OpSpec(
            "delete_retweet",
            is_write=True,
            pack_path=pack_tweet_id_path,
            pack_body=pack_empty_body,
        ),
        _OpSpec(
            "bookmark",
            is_write=True,
            pack_path=pack_tweet_id_path,
            pack_body=pack_empty_body,
        ),
        _OpSpec(
            "delete_bookmark",
            is_write=True,
            pack_path=pack_tweet_id_path,
            pack_body=pack_empty_body,
        ),
        _OpSpec(
            "create_tweet_or_reply",
            browser_social_op="post",
            is_write=True,
            pack_body=pack_create_body,
        ),
        _OpSpec("create_quote_tweet", is_write=True, pack_body=pack_quote_body),
        _OpSpec(
            "create_tweet_thread",
            browser_social_op="post",
            is_write=True,
            pack_body=pack_thread_body,
        ),
        _OpSpec("delete_tweets", is_write=True, pack_body=pack_delete_body),
        _OpSpec(
            "post_tweet_auto_cookie",
            browser_social_op="post",
            is_write=True,
            pack_body=pack_auto_cookie_body,
        ),
        _OpSpec(
            "get_users_by_usernames",
            twex_key="users",
            pack_body=pack_users_body,
        ),
        _OpSpec("follow_user", is_write=True, pack_body=pack_follow_body),
        _OpSpec(
            "fetch_article_markdown",
            pack_path=pack_tweet_id_path,
        ),
        _OpSpec(
            "home_timeline_collect",
            twex_key="timeline_page",
            browser_social_op="home_feed",
            pack_path=pack_timeline_path,
            pack_body=pack_empty_body,
        ),
        _OpSpec("session_status"),
        _OpSpec(
            "comment_on_tweet",
            twex_key="create_tweet_or_reply",
            browser_social_op="reply",
            is_write=True,
            pack_body=pack_comment_body,
        ),
        _OpSpec(
            "react_tweet",
            twex_key="like_tweet",
            is_write=True,
            pack_path=pack_tweet_id_path,
            pack_body=pack_empty_body,
        ),
        _OpSpec(
            "collect_tweet_replies",
            twex_key="replies_page",
            browser_social_op="read_replies",
            pack_path=pack_tweet_id_path,
            pack_body=pack_replies_body,
        ),
        _OpSpec(
            "get_tweet_stats",
            twex_key="tweet_detail",
            browser_social_op="read",
            pack_body=pack_tweet_detail_body,
        ),
        _OpSpec(
            "get_new_comments_on_tweet",
            twex_key="replies_page",
            browser_social_op="read_replies",
            pack_path=pack_tweet_id_path,
            pack_body=pack_replies_body,
        ),
        _OpSpec(
            "discover_followers",
            twex_key="users",
            browser_social_op="search",
            pack_body=pack_discover_followers_body,
        ),
        _OpSpec(
            "discover_topic_accounts",
            twex_key="search_page",
            browser_social_op="search",
            pack_body=pack_discover_topic_body,
        ),
        _OpSpec(
            "discover_mutual_graph",
            twex_key="users",
            browser_social_op="search",
            pack_body=pack_discover_mutual_body,
        ),
    )
}

FACADE_OPS: frozenset[str] = frozenset(_OP_SPECS)

# W12-W14 #129 expansion ops (incremental ship per D11).
W12_ENGAGEMENT_OPS: frozenset[str] = frozenset({"comment_on_tweet", "react_tweet"})
W13_TIMELINE_OPS: frozenset[str] = frozenset(
    {"get_new_comments_on_tweet", "get_tweet_stats", "collect_tweet_replies"}
)
W14_DISCOVERY_OPS: frozenset[str] = frozenset(
    {"discover_followers", "discover_topic_accounts", "discover_mutual_graph"}
)
EXPANSION_OPS: frozenset[str] = W12_ENGAGEMENT_OPS | W13_TIMELINE_OPS | W14_DISCOVERY_OPS


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


def envelope(
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
        >>> envelope(ok=True, medium="browser", op="session_status", data={})["ok"]
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


def smm_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    """Extract the ``skills.social_media_manager`` block when present.

    Args:
        cfg (dict[str, Any]): Full workspace cfg, SMM block, or test stub.

    Returns:
        dict[str, Any]: Medium-resolution config mapping.

    Examples:
        >>> smm_cfg({"default_medium": "browser"})["default_medium"]
        'browser'
    """
    skills = cfg.get("skills")
    if isinstance(skills, dict):
        block = skills.get("social_media_manager")
        if isinstance(block, dict):
            return block
    return cfg


def _browser_tools_section(cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Return ``tools.browser`` from ``cfg`` when present.

    Args:
        cfg (dict[str, Any]): Config tree.

    Returns:
        dict[str, Any] | None: Browser tools section or ``None``.

    Examples:
        >>> _browser_tools_section({"tools": {"browser": {"cdp": True}}})["cdp"]
        True
    """
    tools = cfg.get("tools")
    if not isinstance(tools, dict):
        return None
    browser = tools.get("browser")
    return browser if isinstance(browser, dict) else None


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


def _task_force_rate_limit(task: dict[str, Any]) -> bool:
    """Return whether the task simulates a rate-limit response (tests / guardrails).

    Args:
        task (dict[str, Any]): Task payload.

    Returns:
        bool: True when ``force_rate_limit`` is truthy.

    Examples:
        >>> _task_force_rate_limit({"force_rate_limit": True})
        True
    """
    raw = task.get("force_rate_limit")
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(raw)


def _rate_limit_envelope(op: str, medium: str, *, retry_after_s: int = 30) -> dict[str, Any]:
    """Build a machine-readable rate-limit envelope for discovery ops (D11).

    Args:
        op (str): Facade op name.
        medium (str): Resolved medium.
        retry_after_s (int): Suggested backoff seconds.

    Returns:
        dict[str, Any]: Failure envelope with ``code=RATE_LIMITED``.

    Examples:
        >>> _rate_limit_envelope("discover_followers", "twexapi")["code"]
        'RATE_LIMITED'
    """
    return envelope(
        ok=False,
        medium=medium,
        op=op,
        data={"retry_after_s": retry_after_s},
        error="rate limited — retry after backoff",
        code="RATE_LIMITED",
    )


def _task_dry_run(task: dict[str, Any]) -> bool:
    """Return whether the task requests a dry-run (no live writes).

    Args:
        task (dict[str, Any]): Task payload.

    Returns:
        bool: True when ``dry_run`` is truthy.

    Examples:
        >>> _task_dry_run({"dry_run": True})
        True
    """
    raw = task.get("dry_run")
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(raw)


def _dry_run_envelope(op: str, medium: str, task: dict[str, Any]) -> dict[str, Any]:
    """Build a planned-action envelope for write/read ops under dry-run (D11).

    Args:
        op (str): Facade op name.
        medium (str): Resolved medium.
        task (dict[str, Any]): Task payload (secrets omitted from ``data.task``).

    Returns:
        dict[str, Any]: Success envelope with ``code=DRY_RUN``.

    Examples:
        >>> _dry_run_envelope("react_tweet", "browser", {"dry_run": True})["code"]
        'DRY_RUN'
    """
    safe_task = {k: v for k, v in task.items() if k not in ("cookie", "export_cookies", "cookies")}
    planned: dict[str, Any] = {"dry_run": True, "planned": True, "task": safe_task}
    if op in W13_TIMELINE_OPS:
        planned["read"] = True
    if op in W14_DISCOVERY_OPS:
        planned["read"] = True
        planned["discovery"] = True
    return envelope(
        ok=True,
        medium=medium,
        op=op,
        data=planned,
        code="DRY_RUN",
    )


def _reply_item_id(item: Any) -> str | None:
    """Extract a reply tweet id from a TwexAPI/browser reply item.

    Args:
        item (Any): Reply record.

    Returns:
        str | None: Tweet id when present.

    Examples:
        >>> _reply_item_id({"id": "9"})
        '9'
    """
    if not isinstance(item, dict):
        return None
    for key in ("id", "tweet_id", "rest_id", "id_str"):
        raw = item.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return None


def _extract_reply_items(data: Any) -> list[Any]:
    """Return a reply list from common TwexAPI/browser payload shapes.

    Args:
        data (Any): API or parsed browser payload.

    Returns:
        list[Any]: Reply items (may be empty).

    Examples:
        >>> _extract_reply_items({"replies": [{"id": "1"}]})[0]["id"]
        '1'
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("replies", "comments", "items", "tweets", "data"):
            raw = data.get(key)
            if isinstance(raw, list):
                return raw
    return []


def _filter_new_comments(data: Any, task: dict[str, Any]) -> Any:
    """Keep only replies newer than ``since_id`` / ``last_seen_id`` when set.

    Args:
        data (Any): Raw replies payload.
        task (dict[str, Any]): Task with optional ``since_id`` / ``last_seen_id``.

    Returns:
        Any: Filtered payload (same top-level shape when possible).

    Examples:
        >>> out = _filter_new_comments(
        ...     {"replies": [{"id": "2"}, {"id": "1"}]},
        ...     {"since_id": "1"},
        ... )
        >>> out["replies"][0]["id"]
        '2'
    """
    since_raw = (
        task.get("since_id") if task.get("since_id") is not None else task.get("last_seen_id")
    )
    if since_raw is None or not str(since_raw).strip():
        return data
    since_s = str(since_raw).strip()
    items = _extract_reply_items(data)
    if not items:
        return data
    filtered: list[Any] = []
    for item in items:
        reply_id = _reply_item_id(item)
        if reply_id is None:
            filtered.append(item)
            continue
        try:
            if int(reply_id) > int(since_s):
                filtered.append(item)
        except ValueError:
            if reply_id != since_s:
                filtered.append(item)
    if isinstance(data, list):
        return filtered
    if isinstance(data, dict):
        out = dict(data)
        for key in ("replies", "comments", "items", "tweets", "data"):
            if key in out and isinstance(out[key], list):
                out[key] = filtered
                break
        else:
            out["items"] = filtered
        out["filtered_since_id"] = since_s
        out["new_count"] = len(filtered)
        return out
    return data


def resolve_content_root(task: dict[str, Any]) -> Path:
    """Resolve workspace content root from the task or cwd.

    Args:
        task (dict[str, Any]): Task payload (optional ``content_root``).

    Returns:
        Path: Absolute content root.

    Examples:
        >>> resolve_content_root({}).is_absolute()
        True
    """
    content_root_raw = task.get("content_root")
    if content_root_raw:
        return Path(str(content_root_raw)).expanduser().resolve()
    return Path.cwd()


def _browser_plan(op: str, task: dict[str, Any], site: str, social_op: str) -> dict[str, Any]:
    """Build a CDP ``browser`` tool plan for the parent turn.

    Args:
        op (str): Facade op name.
        task (dict[str, Any]): Task args.
        site (str): Site key.
        social_op (str): Mapped ``SocialRecipe`` op.

    Returns:
        dict[str, Any]: Plan payload for ``action=social``.

    Examples:
        >>> _browser_plan("home_timeline_collect", {}, "x", "home_feed")["action"]
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
    if op in W14_DISCOVERY_OPS:
        plan["discovery"] = True
        for key in ("max_items", "next_cursor", "cursor", "usernames"):
            if task.get(key) is not None:
                plan[key] = task[key]
    return plan


async def _session_status(
    task: dict[str, Any],
    cfg: dict[str, Any],
    site: str,
) -> dict[str, Any]:
    """Report CDP reachability, profile, login probe, and TwexAPI key presence.

    Args:
        task (dict[str, Any]): Optional ``content_root``.
        cfg (dict[str, Any]): Config / test stub.
        site (str): Platform site key for login probe.

    Returns:
        dict[str, Any]: Normalized envelope with readiness fields under ``data``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_session_status)
        True
    """
    medium = resolve_social_medium(task, smm_cfg(cfg), site)
    content_root = resolve_content_root(task)
    try:
        snap = build_social_media_readiness_sync(content_root, site=site)
    except (OSError, ValueError, RuntimeError) as exc:
        return envelope(
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
    return envelope(ok=True, medium=medium, op="session_status", data=data)


async def _dispatch(
    op: str,
    task: dict[str, Any],
    cfg: dict[str, Any],
    site: str,
    *,
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
    if op == "session_status":
        return await _session_status(task, cfg, site)

    spec = _OP_SPECS[op]
    is_write = spec.is_write
    medium = resolve_social_medium(task, smm_cfg(cfg), site)

    if op in W14_DISCOVERY_OPS and _task_force_rate_limit(task):
        retry_raw = task.get("retry_after_s")
        retry_after_s = int(retry_raw) if retry_raw is not None else 30
        return _rate_limit_envelope(op, medium, retry_after_s=retry_after_s)

    if is_write and _task_dry_run(task):
        return _dry_run_envelope(op, medium, task)

    if op in W13_TIMELINE_OPS and _task_dry_run(task):
        return _dry_run_envelope(op, medium, task)

    if op in W14_DISCOVERY_OPS and _task_dry_run(task):
        return _dry_run_envelope(op, medium, task)

    if op == "post_tweet_auto_cookie" and medium == "browser":
        coerced = await _dispatch(
            "create_tweet_or_reply",
            {**task, "medium": "browser"},
            cfg,
            site,
            twexapi_body=twexapi_body,
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

    if medium == "browser" and spec.browser_social_op is None:
        return envelope(
            ok=False,
            medium="browser",
            op=op,
            data={},
            error=(
                f"{op} is not supported on medium=browser "
                "(SocialRecipe: read|post|reply|read_replies|search|"
                "timeline_collect|home_feed) — use medium=twexapi"
            ),
            code="BROWSER_OP_UNSUPPORTED",
        )

    if (
        is_write
        and medium == "browser"
        and not social_write_allowed(site, browser_tools=_browser_tools_section(cfg))
    ):
        return envelope(
            ok=False,
            medium=medium,
            op=op,
            data={},
            error=f"browser write disabled — set tools.browser.social.{site}.allow_write=true",
            code="WRITE_DISABLED",
        )

    if medium == "twexapi":
        content_root = resolve_content_root(task)
        settings, _ = load_twexapi_settings(content_root)
        if not settings.enabled:
            return envelope(
                ok=False,
                medium=medium,
                op=op,
                data={},
                error="TwexAPI medium disabled",
                code="TWEXAPI_DISABLED",
            )
        try:
            api_key = await resolve_twexapi_api_key(content_root=content_root, settings=settings)
        except TwexApiError as exc:
            return envelope(
                ok=False,
                medium=medium,
                op=op,
                data={},
                error=str(exc),
                code="KEY_MISSING",
            )
        twex_key = spec.twexapi_op
        try:
            client = TwexApiClient(api_key, base_url=settings.base_url)
            body = twexapi_body
            path_params = twexapi_path_params
            params = twexapi_params
            write_via_helper = is_write and twex_key in TWEXAPI_WRITE_OPS
            if write_via_helper:
                cookie = _task_cookie(task)
                proxy = _task_proxy(task)
                if not cookie:
                    return envelope(
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
            if op == "get_new_comments_on_tweet":
                data = _filter_new_comments(data, task)
            return envelope(ok=True, medium=medium, op=op, data=data)
        except TwexApiError as exc:
            return envelope(
                ok=False,
                medium=medium,
                op=op,
                data={},
                error=str(exc),
                code="TWEXAPI_ERROR",
            )
        except (OSError, ValueError, RuntimeError) as exc:
            return envelope(
                ok=False,
                medium=medium,
                op=op,
                data={},
                error=str(exc),
                code="TWEXAPI_ERROR",
            )

    if op in ("create_tweet_thread", "comment_on_tweet") and not (
        thread_items(task) if op == "create_tweet_thread" else str(task.get("text") or "").strip()
    ):
        err = (
            "create_tweet_thread on browser requires items/texts in the task"
            if op == "create_tweet_thread"
            else "comment_on_tweet on browser requires text in the task"
        )
        return envelope(
            ok=False,
            medium="browser",
            op=op,
            data={},
            error=err,
            code="BROWSER_OP_UNSUPPORTED",
        )
    social_op = spec.browser_social_op
    if social_op is None:
        return envelope(
            ok=False,
            medium="browser",
            op=op,
            data={},
            error=f"{op} has no browser SocialRecipe mapping — use medium=twexapi",
            code="BROWSER_OP_UNSUPPORTED",
        )
    plan = _browser_plan(op, task, site, social_op)
    return envelope(ok=True, medium="browser", op=op, data={"browser_plan": plan})


async def run_op(
    op: str,
    task: dict[str, Any] | None,
    cfg: dict[str, Any] | None,
    site: str,
    *,
    twexapi_body: dict[str, Any] | list[Any] | None = None,
    twexapi_path_params: dict[str, str] | None = None,
    twexapi_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize args and dispatch one facade op.

    When ``twexapi_body`` / ``twexapi_path_params`` are omitted, OpSpec packers
    derive them from ``task`` (single packing source for public wrappers + worker).

    Args:
        op (str): Facade op name.
        task (dict[str, Any] | None): Task payload.
        cfg (dict[str, Any] | None): Config / test stub.
        site (str): Platform site key.
        twexapi_body (dict[str, Any] | list[Any] | None): TwexAPI JSON body.
        twexapi_path_params (dict[str, str] | None): Path params.
        twexapi_params (dict[str, Any] | None): Query params.

    Returns:
        dict[str, Any]: Normalized envelope.

    Raises:
        KeyError: When ``op`` is not a known facade op.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_op)
        True
    """
    task_d = dict(task or {})
    cfg_d = dict(cfg or {})
    if op not in _OP_SPECS:
        msg = f"unknown facade op: {op!r}"
        raise KeyError(msg)
    medium = resolve_social_medium(task_d, smm_cfg(cfg_d), site)
    if op in W14_DISCOVERY_OPS:
        if _task_force_rate_limit(task_d):
            retry_raw = task_d.get("retry_after_s")
            retry_after_s = int(retry_raw) if retry_raw is not None else 30
            return _rate_limit_envelope(op, medium, retry_after_s=retry_after_s)
        if _task_dry_run(task_d):
            return _dry_run_envelope(op, medium, task_d)
    spec = _OP_SPECS[op]
    try:
        body = twexapi_body
        if body is None and spec.pack_body is not None:
            body = spec.pack_body(task_d)
        path_params = twexapi_path_params
        if path_params is None and spec.pack_path is not None:
            path_params = spec.pack_path(task_d)
    except ValueError as exc:
        medium = resolve_social_medium(task_d, smm_cfg(cfg_d), site)
        err = str(exc)
        code = "TWEET_ID_REQUIRED" if "tweet_id" in err.lower() else "INVALID_TASK"
        return envelope(
            ok=False,
            medium=medium,
            op=op,
            data={},
            error=err,
            code=code,
        )
    return await _dispatch(
        op,
        task_d,
        cfg_d,
        site,
        twexapi_body=body,
        twexapi_path_params=path_params,
        twexapi_params=twexapi_params,
    )
