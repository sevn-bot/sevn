"""Pinned dashboard message publisher (`plan/telegram-commands-design.md` §8.1).

Module: sevn.gateway.dashboard.dashboard_pin
Depends: asyncio, sevn.gateway.runtime.rate_limit

Exports:
    DashboardPinPublisher — per-topic debounced ``editMessageText`` with global cap.
    dashboard_pin_topic_key — stable chat/topic registry key.
    register_dashboard_pin — record pin message id on router.
    lookup_dashboard_pin_message_id — read registered pin id.
    unregister_dashboard_pin — drop registry entry.
    render_dashboard_pin — immediate pin body + keyboard edit.
    default_pin_keyboard — default owner pinned-dashboard keyboard.
    default_pin_text — render pinned caption with state chips.
Examples:
    >>> from sevn.gateway.dashboard.dashboard_pin import DashboardPinPublisher
    >>> pub = DashboardPinPublisher(debounce_s=2.0)
    >>> pub.debounce_s
    2.0
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, cast

from loguru import logger

from sevn.gateway.runtime.rate_limit import TokenBucketLimiter

EditFn = Callable[..., Awaitable[bool]]


def dashboard_pin_topic_key(*, chat_id: int, topic_id: int | None) -> str:
    """Build the registry key for one chat/topic dashboard pin.

    Args:
        chat_id (int): Telegram chat id.
        topic_id (int | None): Forum topic id when applicable.

    Returns:
        str: Stable key into ``ChannelRouter._telegram_dashboard_pins``.

    Examples:
        >>> dashboard_pin_topic_key(chat_id=42, topic_id=None)
        '42:0'
        >>> dashboard_pin_topic_key(chat_id=42, topic_id=7)
        '42:7'
    """
    tid = topic_id if topic_id is not None else 0
    return f"{chat_id}:{tid}"


def register_dashboard_pin(
    router: Any,
    *,
    chat_id: int,
    topic_id: int | None,
    message_id: int,
) -> None:
    """Record one dashboard pin message id for a chat/topic pair.

    Args:
        router (object): Gateway router carrying ``_telegram_dashboard_pins``.
        chat_id (int): Telegram chat id.
        topic_id (int | None): Forum topic id when applicable.
        message_id (int): Pinned Telegram message id.

    Examples:
        >>> class _R:
        ...     _telegram_dashboard_pins: dict[str, int] = {}
        >>> register_dashboard_pin(_R(), chat_id=1, topic_id=None, message_id=9)
        >>> _R._telegram_dashboard_pins
        {'1:0': 9}
    """
    pins = getattr(router, "_telegram_dashboard_pins", None)
    if not isinstance(pins, dict):
        pins = {}
        router._telegram_dashboard_pins = pins
    key = dashboard_pin_topic_key(chat_id=chat_id, topic_id=topic_id)
    pins[key] = message_id


def lookup_dashboard_pin_message_id(
    router: Any,
    *,
    chat_id: int,
    topic_id: int | None,
) -> int | None:
    """Return the registered pin message id for one chat/topic, if any.

    Args:
        router (object): Gateway router carrying ``_telegram_dashboard_pins``.
        chat_id (int): Telegram chat id.
        topic_id (int | None): Forum topic id when applicable.

    Returns:
        int | None: Registered message id, or ``None`` when absent.

    Examples:
        >>> class _R:
        ...     _telegram_dashboard_pins = {"42:0": 1001}
        >>> lookup_dashboard_pin_message_id(_R(), chat_id=42, topic_id=None)
        1001
    """
    pins = getattr(router, "_telegram_dashboard_pins", None)
    if not isinstance(pins, dict):
        return None
    key = dashboard_pin_topic_key(chat_id=chat_id, topic_id=topic_id)
    pin_id = pins.get(key)
    return pin_id if isinstance(pin_id, int) else None


def unregister_dashboard_pin(
    router: Any,
    *,
    chat_id: int,
    topic_id: int | None,
) -> int | None:
    """Remove one dashboard pin registry entry and return the former message id.

    Args:
        router (object): Gateway router carrying ``_telegram_dashboard_pins``.
        chat_id (int): Telegram chat id.
        topic_id (int | None): Forum topic id when applicable.

    Returns:
        int | None: Removed message id, or ``None`` when no entry existed.

    Examples:
        >>> class _R:
        ...     _telegram_dashboard_pins = {"42:0": 1001}
        >>> unregister_dashboard_pin(_R(), chat_id=42, topic_id=None)
        1001
        >>> _R._telegram_dashboard_pins
        {}
    """
    pins = getattr(router, "_telegram_dashboard_pins", None)
    if not isinstance(pins, dict):
        return None
    key = dashboard_pin_topic_key(chat_id=chat_id, topic_id=topic_id)
    removed = pins.pop(key, None)
    return removed if isinstance(removed, int) else None


async def render_dashboard_pin(
    adapter: Any,
    *,
    chat_id: int,
    topic_id: int | None,
    message_id: int,
    model_id: str,
    voice_mode: str,
) -> bool:
    """Immediately edit a dashboard pin message with current chips + keyboard.

    Args:
        adapter (object): Channel adapter exposing Bot API helpers.
        chat_id (int): Telegram chat id.
        topic_id (int | None): Forum topic id when applicable.
        message_id (int): Pin message id to edit.
        model_id (str): Active tier-B model id.
        voice_mode (str): Current TTS mode label.

    Returns:
        bool: ``True`` when an edit API call succeeds.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(render_dashboard_pin)
        True
    """
    text = default_pin_text(model_id=model_id, voice_mode=voice_mode)
    reply_markup = default_pin_keyboard()
    edit_text = getattr(adapter, "edit_message_text", None)
    if callable(edit_text):
        return bool(
            await cast("Callable[..., Awaitable[Any]]", edit_text)(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                message_thread_id=topic_id,
            ),
        )
    api = getattr(adapter, "_api", None)
    if callable(api):
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "reply_markup": reply_markup,
        }
        if topic_id is not None:
            body["message_thread_id"] = topic_id
        res = await cast("Callable[..., Awaitable[Any]]", api)("editMessageText", body)
        return bool(res.get("ok"))
    return False


class DashboardPinPublisher:
    """Coalesce dashboard pin edits per topic with a global token bucket."""

    def __init__(
        self,
        *,
        debounce_s: float = 2.0,
        global_capacity: float = 3.0,
        global_refill_per_second: float = 1.0,
    ) -> None:
        """Initialise debounce and global rate limiter.

        Args:
            debounce_s (float): Minimum seconds between edits per topic key.
            global_capacity (float): Global token bucket capacity.
            global_refill_per_second (float): Global refill rate.

        Examples:
            >>> DashboardPinPublisher(debounce_s=2.0).debounce_s
            2.0
        """
        self.debounce_s = debounce_s
        self._global = TokenBucketLimiter(
            capacity=global_capacity,
            refill_per_second=global_refill_per_second,
        )
        self._pending: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    def _topic_key(self, *, chat_id: int, topic_id: int | None) -> str:
        """Build a stable debounce key for one chat/topic pair.

        Args:
            chat_id (int): Telegram chat id.
            topic_id (int | None): Forum topic id when applicable.

        Returns:
            str: Debounce map key.

        Examples:
            >>> DashboardPinPublisher()._topic_key(chat_id=1, topic_id=7)
            '1:7'
        """
        tid = topic_id if topic_id is not None else 0
        return f"{chat_id}:{tid}"

    async def schedule_render(
        self,
        *,
        chat_id: int,
        topic_id: int | None,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any],
        edit_fn: EditFn,
    ) -> None:
        """Schedule a debounced dashboard pin re-render for one topic.

        Args:
            chat_id (int): Telegram chat id.
            topic_id (int | None): Forum topic id when applicable.
            message_id (int): Pinned message id to edit.
            text (str): Updated caption text.
            reply_markup (dict[str, Any]): Inline keyboard markup.
            edit_fn (EditFn): Async callable performing ``editMessageText``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(DashboardPinPublisher.schedule_render)
            True
        """
        key = self._topic_key(chat_id=chat_id, topic_id=topic_id)

        async def _run() -> None:
            await asyncio.sleep(self.debounce_s)
            allowed = await self._global.allow("dashboard_pin_global")
            if not allowed:
                return
            try:
                await edit_fn(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    reply_markup=reply_markup,
                    message_thread_id=topic_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("dashboard_pin_edit_failed chat_id={}", chat_id)

        async with self._lock:
            existing = self._pending.get(key)
            if existing is not None and not existing.done():
                existing.cancel()
            task = asyncio.create_task(_run())
            self._pending[key] = task


def default_pin_keyboard() -> dict[str, Any]:
    """Return the default owner pinned-dashboard inline keyboard.

    Returns:
        dict[str, Any]: Bot API ``InlineKeyboardMarkup``-shaped dict.

    Examples:
        >>> kb = default_pin_keyboard()
        >>> kb["inline_keyboard"][0][0]["text"]
        '📦 New'
    """
    return {
        "inline_keyboard": [
            [
                {"text": "📦 New", "callback_data": "menu:cmd:new"},
                {"text": "⏹ Stop", "callback_data": "menu:cmd:stop"},
                {"text": "📊 Status", "callback_data": "menu:cmd:status"},
            ],
            [
                {"text": "🧠 Model", "callback_data": "menu:cmd:model"},
                {"text": "⌨️ Shortcuts", "callback_data": "cfg:section:shortcuts"},
            ],
        ],
    }


def default_pin_text(*, model_id: str, voice_mode: str) -> str:
    """Render pinned dashboard caption with state chips.

    Args:
        model_id (str): Active tier-B model id.
        voice_mode (str): Current TTS mode label.

    Returns:
        str: Plain-text pin body.

    Examples:
        >>> "stub/model" in default_pin_text(model_id="stub/model", voice_mode="off")
        True
    """
    return f"sevn dashboard\nModel: {model_id}\nVoice: {voice_mode}"


__all__ = [
    "DashboardPinPublisher",
    "dashboard_pin_topic_key",
    "default_pin_keyboard",
    "default_pin_text",
    "lookup_dashboard_pin_message_id",
    "register_dashboard_pin",
    "render_dashboard_pin",
    "unregister_dashboard_pin",
]
