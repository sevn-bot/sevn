"""Telegram Web + Bot-API assertion helpers replacing ``tools/telegram-tester``.

Host Playwright E2E (``sevn telegram-test``) used to assert send/receive/thread
behaviour on Telegram Web K and probe the bot via the Bot API. Those checks now
live here on top of :class:`~sevn.browser.recipes.telegram_web.TelegramWeb` and a
browser-free ``getMe`` smoke call.

Module: sevn.browser.recipes.telegram_checks
Depends: httpx, sevn.browser.recipes.base, sevn.browser.recipes.telegram_web

Exports:
    TelegramCheckError — raised when a Web or Bot-API expectation fails.
    assert_message_contains — substring match after ``TelegramWeb.read``.
    assert_send_receive — send then assert the chat transcript contains the text.
    bot_api_get_me — Bot-API ``getMe`` smoke (no browser).

Examples:
    >>> TelegramCheckError("x").args[0]
    'x'
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from sevn.browser.recipes.base import RecipeError

if TYPE_CHECKING:
    from sevn.browser.recipes.telegram_web import TelegramWeb

_BOT_API = "https://api.telegram.org"
_GET_ME_TIMEOUT_S = 15.0


class TelegramCheckError(AssertionError):
    """Raised when a Telegram Web or Bot-API expectation is not met."""


async def assert_message_contains(
    tg: TelegramWeb,
    chat: str,
    needle: str,
    *,
    max_chars: int = 8000,
) -> str:
    """Assert the visible transcript for ``chat`` includes ``needle``.

    Args:
        tg (TelegramWeb): Bound Telegram Web recipe.
        chat (str): Chat title or @username.
        needle (str): Expected substring.
        max_chars (int): Cap passed to :meth:`TelegramWeb.read`.

    Returns:
        str: The observed transcript text.

    Raises:
        TelegramCheckError: When ``needle`` is absent.
        RecipeError: When the recipe cannot open or read the chat.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(assert_message_contains)
        True
    """
    out = await tg.read(chat, max_chars=max_chars)
    text = str(out.get("text") or "")
    if needle not in text:
        msg = f"expected chat {chat!r} to contain {needle!r}, got {text!r}"
        raise TelegramCheckError(msg)
    return text


async def assert_send_receive(
    tg: TelegramWeb,
    chat: str,
    text: str,
    *,
    max_chars: int = 8000,
) -> dict[str, Any]:
    """Send ``text`` to ``chat`` and assert the transcript contains it (thread check).

    Args:
        tg (TelegramWeb): Bound Telegram Web recipe.
        chat (str): Chat title or @username.
        text (str): Message body to send and then find.
        max_chars (int): Cap passed to :meth:`TelegramWeb.read`.

    Returns:
        dict[str, Any]: ``{chat, sent, text}`` with the observed transcript.

    Raises:
        TelegramCheckError: When the transcript does not contain ``text``.
        RecipeError: When send or read fails.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(assert_send_receive)
        True
    """
    if not text:
        raise RecipeError("assert_send_receive requires non-empty text")
    await tg.send(chat, text)
    observed = await assert_message_contains(tg, chat, text, max_chars=max_chars)
    return {"chat": chat, "sent": True, "text": observed}


def bot_api_get_me(token: str, *, timeout_s: float = _GET_ME_TIMEOUT_S) -> dict[str, Any]:
    """Call Bot API ``getMe`` (no browser) and return the JSON body.

    Use this for bot-token / connectivity checks that do not need Telegram Web.

    Args:
        token (str): Bot token (never logged by callers).
        timeout_s (float): HTTP timeout in seconds.

    Returns:
        dict[str, Any]: Decoded JSON body (``ok`` / ``result`` / ``description``).

    Raises:
        TelegramCheckError: When ``token`` is empty or the HTTP call fails.
        httpx.HTTPError: Propagated only when transport fails before a body.

    Examples:
        >>> bot_api_get_me("")  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        TelegramCheckError: ...
    """
    cleaned = (token or "").strip()
    if not cleaned:
        raise TelegramCheckError("bot_api_get_me requires a non-empty bot token")
    url = f"{_BOT_API}/bot{cleaned}/getMe"
    try:
        response = httpx.get(url, timeout=timeout_s)
    except httpx.HTTPError as exc:
        msg = f"bot_api_get_me transport failed: {type(exc).__name__}"
        raise TelegramCheckError(msg) from exc
    try:
        data = response.json()
    except ValueError as exc:
        msg = f"bot_api_get_me returned non-JSON (status={response.status_code})"
        raise TelegramCheckError(msg) from exc
    if not isinstance(data, dict):
        raise TelegramCheckError("bot_api_get_me returned a non-object JSON body")
    if not data.get("ok"):
        detail = data.get("description") or f"status={response.status_code}"
        raise TelegramCheckError(f"bot_api_get_me ok=false: {detail}")
    return data


__all__ = [
    "TelegramCheckError",
    "assert_message_contains",
    "assert_send_receive",
    "bot_api_get_me",
]
