"""Forum topic and group resolution helpers for the ``telegram`` skill.

Module: sevn.channels.telegram_skill.forum
Depends: sevn.channels.telegram_skill.hooks

Exports:
    create_forum_topic — ``createForumTopic`` via Bot API hook.
    find_group_by_name — resolve supergroup chat id via userbot/allowlist hook.
"""

from __future__ import annotations

from typing import Any

from sevn.channels.telegram_skill.hooks import TelegramSkillHooks


async def create_forum_topic(
    hooks: TelegramSkillHooks,
    *,
    chat_id: int,
    name: str,
    icon_color: int | None = None,
) -> dict[str, Any]:
    """Create a forum topic in a supergroup via the Bot API hook.

    Args:
        hooks (TelegramSkillHooks): Injectable Bot API delegate.
        chat_id (int): Destination supergroup chat id.
        name (str): Topic title (1-128 chars per Bot API).
        icon_color (int | None, optional): Optional ``icon_color`` field. Defaults to ``None``.

    Returns:
        dict[str, Any]: Normalised result with ``ok``, ``topic_id``, ``message_thread_id``.

    Raises:
        RuntimeError: When no Bot API hook is configured.
        ValueError: When the title is empty or the API rejects the request.

    Examples:
        >>> import asyncio
        >>> from sevn.channels.telegram_skill.hooks import TelegramSkillHooks
        >>> async def _api(_m: str, _b: dict[str, object]) -> dict[str, object]:
        ...     return {
        ...         "ok": True,
        ...         "result": {"message_thread_id": 9, "name": "Infra"},
        ...     }
        >>> out = asyncio.run(
        ...     create_forum_topic(
        ...         TelegramSkillHooks(bot_api=_api),
        ...         chat_id=-1001,
        ...         name="Infra",
        ...     )
        ... )
        >>> out["topic_id"]
        9
    """
    if hooks.bot_api is None:
        msg = "telegram_forum_create: Bot API hook not configured (set SEVN_TELEGRAM_BOT_TOKEN)"
        raise RuntimeError(msg)
    title = name.strip()
    if not title:
        msg = "telegram_forum_create: topic name is required"
        raise ValueError(msg)
    body: dict[str, Any] = {"chat_id": int(chat_id), "name": title[:128]}
    if icon_color is not None:
        body["icon_color"] = int(icon_color)
    res = await hooks.bot_api("createForumTopic", body)
    if not res.get("ok"):
        desc = str(res.get("description") or "createForumTopic failed")
        raise ValueError(desc)
    result = res.get("result")
    if not isinstance(result, dict):
        msg = "telegram_forum_create: missing result payload"
        raise ValueError(msg)
    thread_id = result.get("message_thread_id")
    if thread_id is None:
        msg = "telegram_forum_create: missing message_thread_id"
        raise ValueError(msg)
    return {
        "ok": True,
        "chat_id": int(chat_id),
        "name": str(result.get("name") or title),
        "topic_id": int(thread_id),
        "message_thread_id": int(thread_id),
    }


async def find_group_by_name(hooks: TelegramSkillHooks, *, name: str) -> dict[str, Any]:
    """Resolve a supergroup chat id by display title via the find-group hook.

    Args:
        hooks (TelegramSkillHooks): Injectable userbot or allowlist delegate.
        name (str): Group title substring (case-insensitive).

    Returns:
        dict[str, Any]: ``ok`` plus ``chat_id`` when found.

    Raises:
        RuntimeError: When no find-group hook is configured.
        ValueError: When the name is empty or no group matches.

    Examples:
        >>> import asyncio
        >>> from sevn.channels.telegram_skill.hooks import TelegramSkillHooks
        >>> async def _find(n: str) -> int | None:
        ...     return -10099 if "acme" in n.lower() else None
        >>> out = asyncio.run(
        ...     find_group_by_name(
        ...         TelegramSkillHooks(find_group=_find),
        ...         name="acme2-groups",
        ...     )
        ... )
        >>> out["chat_id"]
        -10099
    """
    if hooks.find_group is None:
        msg = (
            "telegram_forum_find_group: find hook not configured "
            "(userbot or channels.telegram.allowed_groups + bot token)"
        )
        raise RuntimeError(msg)
    needle = name.strip()
    if not needle:
        msg = "telegram_forum_find_group: group name is required"
        raise ValueError(msg)
    chat_id = await hooks.find_group(needle)
    if chat_id is None:
        msg = f"telegram_forum_find_group: no group matched name={needle!r}"
        raise ValueError(msg)
    return {"ok": True, "chat_id": int(chat_id), "name": needle}
