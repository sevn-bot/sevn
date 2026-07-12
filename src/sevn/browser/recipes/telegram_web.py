"""Telegram Web recipe — full control of ``web.telegram.org`` over the CDP engine.

Drives the K-version web app (``/k``, with an ``/a`` fallback): detect login state,
list chats, read a chat, send / reply, search, and read a **BotFather** token — the
exact capability the onboarding wizard uses for Telegram Web automation. Login pauses for
the operator on the QR / phone-code step (``HUMAN_REQUIRED``); no 2FA bypass.

Selectors target Telegram Web K and are kept as named constants because Telegram ships
DOM changes; tune them against a live session (``SEVN_BROWSER_LIVE=1``).

Module: sevn.browser.recipes.telegram_web
Depends: asyncio, re, sevn.browser.element, sevn.browser.page, sevn.browser.recipes.base

Exports:
    TelegramWeb — Telegram Web operations over a page/dom pair.
    extract_bot_token — pull a bot token out of free text.

Examples:
    >>> extract_bot_token("Use this token: 123456789:ABCDEF...") is None
    True
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any, Final

from sevn.browser.recipes.base import RecipeError, human_required

if TYPE_CHECKING:
    from sevn.browser.element import Dom
    from sevn.browser.page import Page

TELEGRAM_EGRESS: Final[tuple[str, ...]] = ("telegram.org", "t.me", "telegram.me")
TELEGRAM_WEB_URL: Final[str] = "https://web.telegram.org/k/"
TELEGRAM_WEB_A_URL: Final[str] = "https://web.telegram.org/a/"

# BotFather bot tokens look like ``<8-10 digits>:<35 url-safe chars>``.
BOT_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"\b(\d{8,10}:[A-Za-z0-9_-]{35})\b")

# Telegram Web K selectors (tune against a live session; see module docstring).
_COMPOSER_SELECTORS: Final[tuple[str, ...]] = (
    ".input-message-input",
    "div.input-message-input[contenteditable=true]",
    "[data-mid] .input-message-input",
)
_SEARCH_SELECTORS: Final[tuple[str, ...]] = (
    "#telegram-search-input",
    ".input-search input",
    "input.input-field-input",
)
_CHAT_ITEM_SELECTOR: Final[str] = "ul.chatlist > a.chatlist-chat, .chatlist .chatlist-chat"
_LOGGED_IN_MARKERS: Final[tuple[str, ...]] = ("#column-left", ".chatlist", ".sidebar-header")
_LOGIN_MARKERS: Final[tuple[str, ...]] = (".qr-container", ".login-page", "[data-qr]")

_TYPE_PAUSE_S: Final[float] = 0.2


def extract_bot_token(text: str) -> str | None:
    """Return the first BotFather token found in ``text``, or ``None``.

    Args:
        text (str): Free text (for example a BotFather chat transcript).

    Returns:
        str | None: The matched ``<id>:<secret>`` token or ``None``.

    Examples:
        >>> extract_bot_token("Done! token is 123456789:" + "A" * 35) == "123456789:" + "A" * 35
        True
        >>> extract_bot_token("no token here") is None
        True
    """
    match = BOT_TOKEN_RE.search(text or "")
    return match.group(1) if match else None


class TelegramWeb:
    """High-level Telegram Web operations over a CDP page + finder."""

    def __init__(self, page: Page, dom: Dom) -> None:
        """Bind a page and finder for the active Telegram Web tab.

        Args:
            page (Page): Page bound to the Telegram Web tab.
            dom (Dom): Finder bound to the same tab.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(TelegramWeb.__init__)
            True
        """
        self._page = page
        self._dom = dom

    async def open(self) -> dict[str, Any]:
        """Navigate to Telegram Web K and report login state.

        Returns:
            dict[str, Any]: ``{url, logged_in}``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramWeb.open)
            True
        """
        await self._page.goto(TELEGRAM_WEB_URL)
        return {"url": await self._page.url(), "logged_in": await self.logged_in()}

    async def logged_in(self) -> bool:
        """Return whether a logged-in Telegram Web session is present.

        Returns:
            bool: ``True`` when a logged-in marker is found and no login form is.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramWeb.logged_in)
            True
        """
        for marker in _LOGGED_IN_MARKERS:
            if await self._page.evaluate(f"!!document.querySelector({marker!r})"):
                return True
        return False

    async def login(self) -> dict[str, Any]:
        """Ensure a logged-in session, pausing for the operator on QR/code (D9).

        Returns:
            dict[str, Any]: ``{logged_in: True}`` or a ``HUMAN_REQUIRED`` handoff.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramWeb.login)
            True
        """
        await self._page.goto(TELEGRAM_WEB_URL)
        if await self.logged_in():
            return {"logged_in": True}
        for marker in _LOGIN_MARKERS:
            if await self._page.evaluate(f"!!document.querySelector({marker!r})"):
                return human_required(
                    "Open Telegram on your phone and scan the QR code (or enter the login code).",
                    url=await self._page.url(),
                )
        return human_required(
            "Complete the Telegram Web login in the browser window.",
            url=await self._page.url(),
        )

    async def _require_login(self) -> None:
        """Raise when not logged in (callers need an authenticated session).

        Returns:
            None

        Raises:
            RecipeError: When no logged-in session is present.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramWeb._require_login)
            True
        """
        if not await self.logged_in():
            msg = "Telegram Web is not logged in (LOGIN_REQUIRED) — run op=login"
            raise RecipeError(msg)

    async def search(self, query: str) -> dict[str, Any]:
        """Type ``query`` into the chat search box.

        Args:
            query (str): Search text (chat name, @username, ...).

        Returns:
            dict[str, Any]: ``{searched: query}``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramWeb.search)
            True
        """
        await self._require_login()
        box = await self._first(_SEARCH_SELECTORS)
        if box is None:
            msg = "search box not found (selectors may need tuning)"
            raise RecipeError(msg)
        await box.fill(query)
        await asyncio.sleep(_TYPE_PAUSE_S)
        return {"searched": query}

    async def open_chat(self, name: str) -> dict[str, Any]:
        """Search for ``name`` and open the first matching chat.

        Args:
            name (str): Chat title or @username to open.

        Returns:
            dict[str, Any]: ``{opened: name}``.

        Raises:
            RecipeError: When no matching chat is found.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramWeb.open_chat)
            True
        """
        await self.search(name)
        await asyncio.sleep(_TYPE_PAUSE_S)
        chat = await self._dom.find_by_text(name)
        if chat is None:
            chat = await self._dom.query(_CHAT_ITEM_SELECTOR)
        if chat is None:
            msg = f"chat not found: {name!r}"
            raise RecipeError(msg)
        await chat.click()
        await asyncio.sleep(_TYPE_PAUSE_S)
        return {"opened": name}

    async def list_chats(self, *, limit: int = 30) -> dict[str, Any]:
        """Return chat-list rows (best-effort titles).

        Args:
            limit (int): Maximum chats to return.

        Returns:
            dict[str, Any]: ``{chats: [...], count}``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramWeb.list_chats)
            True
        """
        await self._require_login()
        titles = await self._page.evaluate(
            "Array.from(document.querySelectorAll("
            f"{_CHAT_ITEM_SELECTOR!r})).slice(0, {int(limit)}).map("
            "el => (el.querySelector('.peer-title, .user-title')?.innerText "
            "|| el.innerText || '').trim()).filter(Boolean)"
        )
        rows = titles if isinstance(titles, list) else []
        return {"chats": rows, "count": len(rows)}

    async def read(self, chat: str, *, max_chars: int = 8000) -> dict[str, Any]:
        """Open ``chat`` and return its visible messages text.

        Args:
            chat (str): Chat title or @username.
            max_chars (int): Cap on returned text.

        Returns:
            dict[str, Any]: ``{chat, text}``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramWeb.read)
            True
        """
        await self.open_chat(chat)
        text = await self._page.extract_text(
            selector=".bubbles, .messages-container", max_chars=max_chars
        )
        if not text:
            text = await self._page.extract_text(max_chars=max_chars)
        return {"chat": chat, "text": text}

    async def send(self, chat: str, text: str) -> dict[str, Any]:
        """Open ``chat``, type ``text`` into the composer, and send it.

        Args:
            chat (str): Chat title or @username.
            text (str): Message body.

        Returns:
            dict[str, Any]: ``{chat, sent: True}``.

        Raises:
            RecipeError: When the composer cannot be found.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramWeb.send)
            True
        """
        await self.open_chat(chat)
        composer = await self._first(_COMPOSER_SELECTORS)
        if composer is None:
            msg = "message composer not found (selectors may need tuning)"
            raise RecipeError(msg)
        await composer.type(text)
        await asyncio.sleep(_TYPE_PAUSE_S)
        await composer.press_key("Enter")
        return {"chat": chat, "sent": True}

    async def reply(self, chat: str, text: str) -> dict[str, Any]:
        """Send ``text`` to ``chat`` (v1 reply = a normal message in the chat).

        Args:
            chat (str): Chat title or @username.
            text (str): Reply body.

        Returns:
            dict[str, Any]: ``{chat, replied: True}``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramWeb.reply)
            True
        """
        out = await self.send(chat, text)
        return {"chat": out["chat"], "replied": True}

    async def botfather_token(self) -> dict[str, Any]:
        """Open @BotFather and extract a bot token from the conversation (W10.2).

        Returns:
            dict[str, Any]: ``{token}`` when found, else ``{token: None, text}``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramWeb.botfather_token)
            True
        """
        await self.open_chat("BotFather")
        text = await self._page.extract_text(
            selector=".bubbles, .messages-container", max_chars=12000
        )
        if not text:
            text = await self._page.extract_text(max_chars=12000)
        token = extract_bot_token(text)
        if token:
            return {"token": token}
        return {"text": text[:2000], "found": False}

    async def _first(self, selectors: tuple[str, ...]) -> Any:
        """Return the first element matching any of ``selectors``.

        Args:
            selectors (tuple[str, ...]): CSS selectors to try in order.

        Returns:
            Any: The first matched element handle, or ``None``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramWeb._first)
            True
        """
        for selector in selectors:
            element = await self._dom.query(selector)
            if element is not None:
                return element
        return None


__all__ = ["BOT_TOKEN_RE", "TELEGRAM_EGRESS", "TelegramWeb", "extract_bot_token"]
