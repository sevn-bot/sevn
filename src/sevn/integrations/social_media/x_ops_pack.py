"""TwexAPI body/path packers and thread helpers for the X ops facade.

Module: sevn.integrations.social_media.x_ops_pack
Depends: (stdlib only)

Exports:
    TwexBodyPacker / TwexPathPacker — packer callables.
    thread_items — ordered thread texts from items/texts.
    pack_empty_body — empty TwexAPI JSON body.
    pack_tweet_id_path — tweet_id path params.
    pack_advanced_search_body — search_page body.
    pack_hashtags_body — hashtags body.
    pack_create_body — create/reply body.
    pack_quote_body — quote-tweet body.
    pack_thread_body — create-thread body.
    pack_delete_body — delete-tweets body.
    pack_auto_cookie_body — pool-cookie post body.
    pack_users_body — usernames list body.
    pack_follow_body — follow-user body.
    pack_timeline_path — timeline screen_name path params.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__all__ = [
    "TwexBodyPacker",
    "TwexPathPacker",
    "pack_advanced_search_body",
    "pack_auto_cookie_body",
    "pack_create_body",
    "pack_delete_body",
    "pack_empty_body",
    "pack_follow_body",
    "pack_hashtags_body",
    "pack_quote_body",
    "pack_thread_body",
    "pack_timeline_path",
    "pack_tweet_id_path",
    "pack_users_body",
    "thread_items",
]

TwexBodyPacker = Callable[[dict[str, Any]], dict[str, Any] | list[Any] | None]
TwexPathPacker = Callable[[dict[str, Any]], dict[str, str] | None]


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


def pack_empty_body(_task: dict[str, Any]) -> dict[str, Any]:
    """Return an empty TwexAPI JSON body.

    Args:
        _task (dict[str, Any]): Unused task payload.

    Returns:
        dict[str, Any]: Empty body.

    Examples:
        >>> pack_empty_body({})
        {}
    """
    return {}


def pack_tweet_id_path(task: dict[str, Any]) -> dict[str, str]:
    """Pack ``tweet_id`` path params for tweet-action ops.

    Args:
        task (dict[str, Any]): Task with required ``tweet_id``.

    Returns:
        dict[str, str]: Path params.

    Raises:
        ValueError: When ``tweet_id`` is missing or blank.

    Examples:
        >>> pack_tweet_id_path({"tweet_id": "9"})["tweet_id"]
        '9'
    """
    tweet_id = str(task.get("tweet_id") or "").strip()
    if not tweet_id:
        msg = "tweet_id is required"
        raise ValueError(msg)
    return {"tweet_id": tweet_id}


def pack_advanced_search_body(task: dict[str, Any]) -> dict[str, Any] | None:
    """Pack TwexAPI ``search_page`` body from task fields.

    Args:
        task (dict[str, Any]): Task with ``query`` / ``searchTerms``.

    Returns:
        dict[str, Any] | None: Body or ``None`` when empty.

    Examples:
        >>> pack_advanced_search_body({"query": "ai"})["searchTerms"]
        ['ai']
    """
    body: dict[str, Any] = {}
    if "searchTerms" in task:
        body["searchTerms"] = task["searchTerms"]
    elif task.get("query"):
        body["searchTerms"] = [str(task["query"])]
    for key in ("sortBy", "next_cursor"):
        if task.get(key):
            body[key] = task[key]
    return body or None


def pack_hashtags_body(task: dict[str, Any]) -> dict[str, Any]:
    """Pack TwexAPI ``hashtags`` body.

    Args:
        task (dict[str, Any]): Task with ``hashtags`` / ``query``.

    Returns:
        dict[str, Any]: ``{\"hashtags\": [...]}``.

    Examples:
        >>> pack_hashtags_body({"query": "ai"})["hashtags"]
        ['ai']
    """
    tags = task.get("hashtags")
    if isinstance(tags, str):
        tags = [tags]
    if not tags and task.get("query"):
        tags = [str(task["query"])]
    return {"hashtags": list(tags or [])}


def pack_create_body(task: dict[str, Any]) -> dict[str, Any]:
    """Pack create-tweet / reply body.

    Args:
        task (dict[str, Any]): Task with ``text`` / ``tweet_content``.

    Returns:
        dict[str, Any]: TwexAPI create body.

    Examples:
        >>> pack_create_body({"text": "hi"})["tweet_content"]
        'hi'
    """
    text = str(task.get("text") or task.get("tweet_content") or "")
    body: dict[str, Any] = {"tweet_content": text}
    for key in ("reply_tweet_id", "media_url"):
        if task.get(key):
            body[key] = task[key]
    return body


def pack_quote_body(task: dict[str, Any]) -> dict[str, Any]:
    """Pack quote-tweet body.

    Args:
        task (dict[str, Any]): Task with text and quote target fields.

    Returns:
        dict[str, Any]: TwexAPI quote body.

    Examples:
        >>> pack_quote_body({"text": "q", "tweet_id": "1"})["tweet_id"]
        '1'
    """
    text = str(task.get("text") or task.get("tweet_content") or "")
    body: dict[str, Any] = {"tweet_content": text}
    for key in ("tweet_id", "quoted_tweet_id", "media_url"):
        if task.get(key):
            body[key] = task[key]
    return body


def pack_thread_body(task: dict[str, Any]) -> dict[str, Any]:
    """Pack tweet-thread body from ``items`` / ``texts``.

    Args:
        task (dict[str, Any]): Task payload.

    Returns:
        dict[str, Any]: ``{\"items\": [...]}``.

    Examples:
        >>> pack_thread_body({"items": ["a"]})["items"]
        ['a']
    """
    return {"items": list(thread_items(task))}


def pack_delete_body(task: dict[str, Any]) -> dict[str, Any]:
    """Pack delete-tweets body.

    Args:
        task (dict[str, Any]): Task with optional id fields.

    Returns:
        dict[str, Any]: Sparse delete body.

    Examples:
        >>> pack_delete_body({"username": "a"})["username"]
        'a'
    """
    return {k: task[k] for k in ("username", "target_id", "tweet_ids") if k in task}


def pack_auto_cookie_body(task: dict[str, Any]) -> dict[str, Any]:
    """Pack pool-cookie post body.

    Args:
        task (dict[str, Any]): Task with ``text`` / ``tweet_content``.

    Returns:
        dict[str, Any]: ``{\"tweet_content\": ...}``.

    Examples:
        >>> pack_auto_cookie_body({"text": "x"})["tweet_content"]
        'x'
    """
    text = str(task.get("text") or task.get("tweet_content") or "")
    return {"tweet_content": text}


def pack_users_body(task: dict[str, Any]) -> list[Any]:
    """Pack usernames list body for TwexAPI ``users``.

    Args:
        task (dict[str, Any]): Task with ``usernames`` / ``query``.

    Returns:
        list[Any]: Username strings.

    Examples:
        >>> pack_users_body({"query": "@bob"})
        ['bob']
    """
    names = task.get("usernames")
    if isinstance(names, str):
        names = [n.strip() for n in names.split(",") if n.strip()]
    if not names and task.get("query"):
        names = [str(task["query"]).lstrip("@")]
    return list(names or [])


def pack_follow_body(task: dict[str, Any]) -> dict[str, Any]:
    """Pack follow-user body.

    Args:
        task (dict[str, Any]): Task with ``username`` / ``query``.

    Returns:
        dict[str, Any]: ``{\"username\": ...}``.

    Examples:
        >>> pack_follow_body({"username": "@a"})["username"]
        'a'
    """
    username = str(task.get("username") or task.get("query") or "").lstrip("@")
    return {"username": username}


def pack_timeline_path(task: dict[str, Any]) -> dict[str, str]:
    """Pack timeline ``screen_name`` path params.

    Args:
        task (dict[str, Any]): Task with optional screen/username.

    Returns:
        dict[str, str]: Path params (default ``home``).

    Examples:
        >>> pack_timeline_path({})["screen_name"]
        'home'
    """
    screen = str(task.get("screen_name") or task.get("username") or "home").lstrip("@")
    return {"screen_name": screen}
