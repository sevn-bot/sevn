"""Internal OpSpec table and dispatch for the X ops facade.

Module: sevn.integrations.social_media.x_ops_dispatch
Depends: sevn.browser.recipes.social, sevn.integrations.social_media.medium,
    sevn.integrations.twexapi

Exports:
    cookies_for_twexapi — map browser export_cookies payload → TwexAPI cookie field.
    cookie_bridge_log_safe — log-safe summary of a cookie export (no secret values).
    envelope — build the normalized X-ops response envelope.
    resolve_content_root — resolve workspace content root from a task.
    run_op — normalize args and dispatch one facade op.
    smm_cfg — extract skills.social_media_manager block.
    thread_items — ordered thread texts from items/texts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sevn.browser.recipes.social import social_write_allowed
from sevn.integrations.social_media.medium import resolve_social_medium
from sevn.integrations.twexapi.client import (
    TWEXAPI_WRITE_OPS,
    TwexApiClient,
    TwexApiError,
)
from sevn.integrations.twexapi.config import (
    load_twexapi_settings,
    resolve_twexapi_api_key,
)

__all__ = [
    "cookie_bridge_log_safe",
    "cookies_for_twexapi",
    "envelope",
    "resolve_content_root",
    "run_op",
    "smm_cfg",
    "thread_items",
]

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

_BROWSER_UNSUPPORTED_OPS: frozenset[str] = frozenset(
    {
        "like_tweet",
        "unlike_tweet",
        "retweet",
        "delete_retweet",
        "bookmark",
        "delete_bookmark",
        "follow_user",
        "delete_tweets",
        "create_quote_tweet",
    }
)


@dataclass(frozen=True, slots=True)
class _OpSpec:
    """Table-driven metadata for one §4 facade op."""

    name: str
    twex_key: str | None = None
    browser_social_op: str | None = None

    @property
    def is_write(self) -> bool:
        """Return whether this op is a write (DB8 / ``_BROWSER_WRITE_OPS``).

        Returns:
            bool: ``True`` when ``name`` is in the write-ops set.

        Examples:
            >>> _OpSpec("like_tweet").is_write
            True
        """
        return self.name in _BROWSER_WRITE_OPS

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
        _OpSpec("advanced_search_page", twex_key="search_page", browser_social_op="search"),
        _OpSpec("search_hashtags", twex_key="hashtags", browser_social_op="search"),
        _OpSpec("like_tweet"),
        _OpSpec("unlike_tweet"),
        _OpSpec("retweet"),
        _OpSpec("delete_retweet"),
        _OpSpec("bookmark"),
        _OpSpec("delete_bookmark"),
        _OpSpec("create_tweet_or_reply", browser_social_op="post"),
        _OpSpec("create_quote_tweet"),
        _OpSpec("create_tweet_thread", browser_social_op="post"),
        _OpSpec("delete_tweets"),
        _OpSpec("post_tweet_auto_cookie", browser_social_op="post"),
        _OpSpec("get_users_by_usernames", twex_key="users", browser_social_op="read"),
        _OpSpec("follow_user"),
        _OpSpec("fetch_article_markdown", browser_social_op="read"),
        _OpSpec(
            "home_timeline_collect",
            twex_key="timeline_page",
            browser_social_op="home_feed",
        ),
        _OpSpec("session_status"),
    )
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


def thread_items(task: dict[str, Any]) -> list[str]:
    """Return ordered thread texts from ``items`` / ``texts``.

    Args:
        task (dict[str, Any]): Task payload.

    Returns:
        list[str]: Thread item strings (may be empty).

    Examples:
        >>> thread_items({"items": ["a", "b"]})
        ['a', 'b']
    """
    items = task.get("items") or task.get("texts") or []
    if isinstance(items, str):
        return [items] if items.strip() else []
    if isinstance(items, list):
        return [str(x) for x in items if str(x).strip()]
    return []


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
    body = task.get("text") or task.get("tweet_content") or ""
    plan: dict[str, Any] = {
        "action": "social",
        "site": site,
        "op": social_op,
        "facade_op": op,
        "query": query,
        "url": task.get("url") or task.get("tweet_url") or "",
        "body": body,
        "tweet_id": task.get("tweet_id") or "",
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
    return plan


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
    spec = _OP_SPECS[op]
    is_write = spec.is_write
    medium = resolve_social_medium(task, smm_cfg(cfg), site)

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

    if medium == "browser" and op in _BROWSER_UNSUPPORTED_OPS:
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

    if op == "create_tweet_thread" and not thread_items(task):
        return envelope(
            ok=False,
            medium="browser",
            op=op,
            data={},
            error="create_tweet_thread on browser requires items/texts in the task",
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

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_op)
        True
    """
    return await _dispatch(
        op,
        dict(task or {}),
        dict(cfg or {}),
        site,
        twexapi_body=twexapi_body,
        twexapi_path_params=twexapi_path_params,
        twexapi_params=twexapi_params,
    )
