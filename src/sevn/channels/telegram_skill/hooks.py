"""Injectable hooks for bundled ``telegram`` skill scripts.

Module: sevn.channels.telegram_skill.hooks
Depends: httpx, json, pathlib, sevn.config.workspace_config, sevn.lcm.script_cli

Exports:
    TelegramSkillHooks — Bot API + userbot delegates for skill scripts.
    resolve_telegram_skill_hooks — build hooks from env and workspace ``sevn.json``.
    bot_api_call_from_token — minimal async Bot API caller for skill subprocesses.
    bot_api_call_from_adapter — wrap a live :class:`~sevn.channels.telegram.TelegramAdapter`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from sevn.lcm.script_cli import workspace_from_env

_BOT_API = "https://api.telegram.org"
BotApiCall = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
FindGroupFn = Callable[[str], Awaitable[int | None]]


class _SupportsBotApi(Protocol):
    """Minimal Bot API surface used by :func:`bot_api_call_from_adapter`."""

    async def _api(self, method: str, body: dict[str, Any]) -> dict[str, Any]:
        """Call one Telegram Bot API method.

        Args:
            method (str): Bot API method name.
            body (dict[str, Any]): JSON request body.

        Returns:
            dict[str, Any]: Decoded Bot API response.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(_SupportsBotApi._api)
            True
        """
        ...


@dataclass
class TelegramSkillHooks:
    """Delegates for telegram skill scripts and tests.

    Attributes:
        bot_api (BotApiCall | None): Async ``(method, body) -> response`` caller.
        find_group (FindGroupFn | None): Resolve supergroup chat id by display title.
    """

    bot_api: BotApiCall | None = None
    find_group: FindGroupFn | None = None


def bot_api_call_from_token(token: str) -> BotApiCall:
    """Build a minimal httpx-based Bot API caller for skill subprocesses.

    Args:
        token (str): Telegram bot token.

    Returns:
        BotApiCall: Async caller returning decoded JSON dicts.

    Examples:
        >>> import inspect
        >>> call = bot_api_call_from_token("test-token")
        >>> inspect.iscoroutinefunction(call)
        True
    """
    tok = token.strip()

    async def _call(method: str, body: dict[str, Any]) -> dict[str, Any]:
        if not tok:
            return {}
        url = f"{_BOT_API}/bot{tok}/{method}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=body)
            try:
                data = response.json()
            except json.JSONDecodeError:
                return {}
        return data if isinstance(data, dict) else {}

    return _call


def bot_api_call_from_adapter(adapter: _SupportsBotApi) -> BotApiCall:
    """Wrap a live :class:`~sevn.channels.telegram.TelegramAdapter` for skill hooks.

    Args:
        adapter (_SupportsBotApi): Connected adapter with ``_api``.

    Returns:
        BotApiCall: Delegates to ``adapter._api``.

    Examples:
        >>> class _A:
        ...     async def _api(self, method: str, body: dict[str, object]) -> dict[str, object]:
        ...         return {"ok": True, "method": method}
        >>> hook = bot_api_call_from_adapter(_A())
        >>> import asyncio
        >>> asyncio.run(hook("getMe", {}))["method"]
        'getMe'
    """
    return adapter._api


async def _find_group_via_allowed_groups(
    *,
    bot_api: BotApiCall,
    allowed_groups: list[int],
    name: str,
) -> int | None:
    """Match a group title against ``channels.telegram.allowed_groups`` via ``getChat``.

    Args:
        bot_api (BotApiCall): Bot API caller.
        allowed_groups (list[int]): Configured supergroup chat ids.
        name (str): Case-insensitive substring to match against chat title.

    Returns:
        int | None: Bot API chat id when matched, else ``None``.

    Examples:
        >>> import asyncio
        >>> async def _fake(_m: str, _b: dict[str, object]) -> dict[str, object]:
        ...     return {"ok": True, "result": {"title": "My Group", "id": -1001}}
        >>> asyncio.run(
        ...     _find_group_via_allowed_groups(
        ...         bot_api=_fake,
        ...         allowed_groups=[-1001],
        ...         name="group",
        ...     )
        ... )
        -1001
    """
    needle = name.strip().casefold()
    if not needle:
        return None
    for chat_id in allowed_groups:
        res = await bot_api("getChat", {"chat_id": int(chat_id)})
        if not res.get("ok"):
            continue
        result = res.get("result")
        if not isinstance(result, dict):
            continue
        title = str(result.get("title") or "").casefold()
        if needle in title or title == needle:
            return int(chat_id)
    return None


def _load_allowed_groups(workspace: Path) -> list[int]:
    """Read ``channels.telegram.allowed_groups`` from workspace ``sevn.json`` when present.

    Args:
        workspace (Path): Workspace content root.

    Returns:
        list[int]: Parsed allowlisted supergroup ids (may be empty).

    Examples:
        >>> _load_allowed_groups(Path("/nonexistent")) == []
        True
    """
    cfg_path = workspace / "sevn.json"
    if not cfg_path.is_file():
        return []
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    channels = raw.get("channels")
    if not isinstance(channels, dict):
        return []
    tg = channels.get("telegram")
    if not isinstance(tg, dict):
        return []
    groups = tg.get("allowed_groups")
    if not isinstance(groups, list):
        return []
    out: list[int] = []
    for item in groups:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def resolve_telegram_skill_hooks(
    workspace: Path | None = None,
    *,
    adapter: _SupportsBotApi | None = None,
    overrides: TelegramSkillHooks | None = None,
) -> TelegramSkillHooks:
    """Resolve default telegram skill hooks for bundled scripts.

    Prefers an injected ``adapter`` or explicit ``overrides``. Otherwise uses
    ``SEVN_TELEGRAM_BOT_TOKEN`` and ``channels.telegram.allowed_groups`` from
    ``sevn.json`` for Bot API + allowlist title scan.

    Args:
        workspace (Path | None, optional): Content root; defaults to :func:`workspace_from_env`.
        adapter (_SupportsBotApi | None, optional): Live gateway adapter when in-process.
        overrides (TelegramSkillHooks | None, optional): Explicit hook bundle for tests.

    Returns:
        TelegramSkillHooks: Resolved hook bundle (callers must handle ``None`` bot_api).

    Examples:
        >>> hooks = resolve_telegram_skill_hooks(Path("."), overrides=TelegramSkillHooks())
        >>> hooks.bot_api is None
        True
    """
    root = workspace if workspace is not None else workspace_from_env()
    if overrides is not None:
        resolved_bot_api = overrides.bot_api
        resolved_find_group = overrides.find_group
        if resolved_find_group is None and resolved_bot_api is not None:
            allowed = _load_allowed_groups(root)
            if allowed:

                async def _find_override(name: str) -> int | None:
                    return await _find_group_via_allowed_groups(
                        bot_api=resolved_bot_api,
                        allowed_groups=allowed,
                        name=name,
                    )

                resolved_find_group = _find_override
        return TelegramSkillHooks(bot_api=resolved_bot_api, find_group=resolved_find_group)
    bot_api: BotApiCall | None
    if adapter is not None:
        bot_api = bot_api_call_from_adapter(adapter)
    else:
        token = os.environ.get("SEVN_TELEGRAM_BOT_TOKEN", "").strip()
        bot_api = bot_api_call_from_token(token) if token else None
    allowed = _load_allowed_groups(root)
    find_group: FindGroupFn | None = None
    if bot_api is not None and allowed:

        async def _find(name: str) -> int | None:
            return await _find_group_via_allowed_groups(
                bot_api=bot_api,
                allowed_groups=allowed,
                name=name,
            )

        find_group = _find
    return TelegramSkillHooks(bot_api=bot_api, find_group=find_group)
