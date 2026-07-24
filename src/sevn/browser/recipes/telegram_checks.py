"""Telegram Web + Bot-API assertion helpers replacing ``tools/telegram-tester``.

The retired host E2E CLI (``sevn telegram-test``) used to assert send/receive/thread
behaviour on Telegram Web K and probe the bot via the Bot API. Those checks now
live here on top of :class:`~sevn.browser.recipes.telegram_web.TelegramWeb` and a
browser-free ``getMe`` smoke call. Operators run them via ``make telegram-checks``
(``python -m sevn.browser.recipes.telegram_checks``) or :func:`run_checks`.

Module: sevn.browser.recipes.telegram_checks
Depends: httpx, sevn.browser.recipes.base, sevn.browser.recipes.telegram_web

Exports:
    TelegramCheckError — raised when a Web or Bot-API expectation fails.
    assert_message_contains — substring match after ``TelegramWeb.read``.
    assert_send_receive — send then assert the chat transcript contains the text.
    bot_api_get_me — Bot-API ``getMe`` smoke (no browser).
    run_checks — operator entry that wires Bot-API and/or send/receive.
    main — CLI entry for ``python -m sevn.browser.recipes.telegram_checks``.

Examples:
    >>> TelegramCheckError("x").args[0]
    'x'
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import TYPE_CHECKING, Any

import httpx

from sevn.browser.recipes.base import RecipeError

if TYPE_CHECKING:
    from sevn.browser.recipes.telegram_web import TelegramWeb

_BOT_API = "https://api.telegram.org"
_GET_ME_TIMEOUT_S = 15.0
_ENV_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"  # nosec B105 — env var name, not a secret value


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


async def run_checks(
    *,
    token: str | None = None,
    tg: TelegramWeb | None = None,
    chat: str = "Saved Messages",
    text: str | None = None,
) -> dict[str, Any]:
    """Run operator Telegram verification (Bot API and/or Web send/receive).

    This is the runnable replacement for the removed ``make telegram-e2e`` /
    ``sevn telegram-test`` harness. When ``tg`` is provided, delegates to
    :func:`assert_send_receive` so the send/receive path is exercised.

    Args:
        token (str | None): Bot token for ``getMe`` (browser-free).
        tg (TelegramWeb | None): Bound Telegram Web recipe for send/receive.
        chat (str): Chat title or @username for send/receive.
        text (str | None): Message body; required when ``tg`` is set.

    Returns:
        dict[str, Any]: ``{ok: True, checks: {...}}`` with completed check payloads.

    Raises:
        TelegramCheckError: When no checks are requested or a check fails.
        RecipeError: When send/receive cannot complete.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_checks)
        True
    """
    checks: dict[str, Any] = {}
    if token is not None:
        checks["bot_api_get_me"] = bot_api_get_me(token)
    if tg is not None:
        if not text:
            raise RecipeError("run_checks with tg requires non-empty text")
        checks["assert_send_receive"] = await assert_send_receive(tg, chat, text)
    if not checks:
        raise TelegramCheckError(
            "run_checks requires a bot token and/or a TelegramWeb recipe with text"
        )
    return {"ok": True, "checks": checks}


def main(argv: list[str] | None = None) -> int:
    """CLI entry for host Telegram verification (``make telegram-checks``).

    Browser-free path: Bot-API ``getMe`` via ``--token`` or ``TELEGRAM_BOT_TOKEN``.
    Web send/receive uses :func:`run_checks` from Python with a bound
    :class:`~sevn.browser.recipes.telegram_web.TelegramWeb` (CDP session).

    Args:
        argv (list[str] | None): CLI args excluding program name; ``None`` →
            ``sys.argv[1:]``.

    Returns:
        int: Process exit code (0 success, 1 failure).

    Examples:
        >>> import inspect
        >>> inspect.signature(main).parameters["argv"].annotation
        'list[str] | None'
    """
    parser = argparse.ArgumentParser(
        prog="python -m sevn.browser.recipes.telegram_checks",
        description=(
            "Host Telegram verification (replaces make telegram-e2e). "
            "Runs Bot-API getMe when a token is provided."
        ),
    )
    parser.add_argument(
        "--token",
        default=os.environ.get(_ENV_BOT_TOKEN, ""),
        help=f"Bot token (default: ${_ENV_BOT_TOKEN})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the check result as JSON on stdout",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    token = (args.token or "").strip()
    if not token:
        parser.error(f"provide --token or set {_ENV_BOT_TOKEN}")
    try:
        result = asyncio.run(run_checks(token=token))
    except (TelegramCheckError, RecipeError, httpx.HTTPError) as exc:
        sys.stderr.write(f"telegram_checks failed: {exc}\n")
        return 1
    if args.json:
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    else:
        me = result["checks"]["bot_api_get_me"]
        username = (me.get("result") or {}).get("username") or "?"
        sys.stdout.write(f"bot_api_get_me ok — @{username}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "TelegramCheckError",
    "assert_message_contains",
    "assert_send_receive",
    "bot_api_get_me",
    "main",
    "run_checks",
]
