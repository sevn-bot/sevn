"""High-level Telegram Web K interactions for E2E tests.

Discovered via Playwright MCP against web.telegram.org/k (2026-05):
- Hash-only navigation does not always open the center column; click the sidebar chat row.
- Real composer is ``.input-message-input[data-peer-id]`` (not ``.input-field-input-fake``).
- Message bodies use ``.bubble-content`` inside ``#column-center .bubbles``.
- Active inline keyboard is the **last** ``.reply-markup`` block in the chat column.

Module: sevn_telegram_tester.telegram_client
Depends: playwright.sync_api

Exports:
    SELECTORS — CSS hooks for Telegram Web K.
    TelegramClient — open chats, send messages, read bubbles.
"""

from __future__ import annotations

import contextlib
import re
import time
from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from sevn_telegram_tester.page_setup import prepare_chat_layout

# Telegram Web K (web.telegram.org/k)
SELECTORS: dict[str, str] = {
    "qr_login": "canvas.qr",
    "left_column": "#column-left",
    "center_column": "#column-center",
    "chat_list": "#column-left .chatlist",
    "chat_list_item": "#column-left .chatlist .chatlist-chat",
    "chat_input_row": "#column-center .chat-input",
    "composer_peer": "#column-center .chat-input .input-message-input[data-peer-id]",
    "bubbles_scroll": "#column-center .bubbles .scrollable",
    "chat_bubbles": "#column-center .bubbles .bubble-content",
    "inline_button": "#column-center .reply-markup-button",
    "bot_start_button": (
        '#column-center button:has-text("START"), '
        '#column-center button:has-text("Start"), '
        "#column-center .chat-input-control-button"
    ),
}


class TelegramClient:
    """Drive Telegram Web K against a target bot chat."""

    def __init__(self, page: Page, *, bot_username: str) -> None:
        self._page = page
        self._bot_username = bot_username.lstrip("@")

    @property
    def bot_username(self) -> str:
        """Target bot handle without leading ``@``."""
        return self._bot_username

    def bot_chat_url(self, *, base_url: str | None = None) -> str:
        """Deep-link URL for Telegram Web K chat with the target bot."""
        root = (base_url or "https://web.telegram.org/k").split("#")[0].rstrip("/")
        return f"{root}/#@{self._bot_username}"

    def bot_chat_url_tgaddr(self, *, base_url: str | None = None) -> str:
        """Resolve-style deep link (Web K ``#?tgaddr=`` route)."""
        root = (base_url or "https://web.telegram.org/k").split("#")[0].rstrip("/")
        tgaddr = quote(f"tg://resolve?domain={self._bot_username}", safe="")
        return f"{root}/#?tgaddr={tgaddr}"

    def open_bot_chat(self, *, timeout_ms: int = 60_000) -> None:
        """Open the target bot chat and ensure the center column + composer are usable."""
        if self._activate_bot_chat(timeout_ms=timeout_ms):
            self._wait_for_composer(timeout_ms=timeout_ms)
            return

        base = self._telegram_k_base_url()
        per_try_ms = max(timeout_ms // 3, 20_000)
        for url in (
            self.bot_chat_url(base_url=base),
            self.bot_chat_url_tgaddr(base_url=base),
        ):
            self._goto_chat_url(url, timeout_ms=per_try_ms)
            if self._activate_bot_chat(timeout_ms=per_try_ms):
                self._wait_for_composer(timeout_ms=timeout_ms)
                return

        self._open_via_search(timeout_ms=timeout_ms)
        self._wait_for_composer(timeout_ms=timeout_ms)

    def _telegram_k_base_url(self) -> str:
        url = self._page.url
        if "web.telegram.org" in url:
            return url.split("#")[0].rstrip("/")
        return "https://web.telegram.org/k"

    def _goto_chat_url(self, url: str, *, timeout_ms: int) -> None:
        self._page.goto(url, wait_until="domcontentloaded")
        with contextlib.suppress(PlaywrightTimeoutError):
            self._page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 20_000))
        self._page.wait_for_timeout(800)

    def _activate_bot_chat(self, *, timeout_ms: int) -> bool:
        """Click the bot in the sidebar and wait for the center chat column."""
        pattern = re.compile(re.escape(self._bot_username), re.IGNORECASE)
        link = self._page.locator(SELECTORS["chat_list_item"]).filter(has_text=pattern)
        if link.count() == 0:
            link = self._page.get_by_role("link", name=pattern)
        if link.count() == 0:
            return False
        link.first.click(timeout=timeout_ms)
        self._page.wait_for_timeout(500)
        self._click_start_if_needed(timeout_ms=timeout_ms)
        try:
            self._page.locator(SELECTORS["center_column"]).wait_for(
                state="visible",
                timeout=min(timeout_ms, 15_000),
            )
        except PlaywrightTimeoutError:
            return False
        prepare_chat_layout(self._page)
        return self._composer().count() > 0

    def _open_via_search(self, *, timeout_ms: int) -> None:
        from sevn_telegram_tester.auth import wait_for_main_ui

        base = self._telegram_k_base_url()
        self._page.goto(f"{base}/", wait_until="domcontentloaded")
        wait_for_main_ui(self._page, timeout_ms=timeout_ms)

        search = self._page.locator(SELECTORS["left_column"]).get_by_role("textbox").first
        search.click(timeout=timeout_ms)
        search.fill(f"@{self._bot_username}", timeout=timeout_ms)
        self._page.wait_for_timeout(600)
        self._activate_bot_chat(timeout_ms=timeout_ms)

    def _click_start_if_needed(self, *, timeout_ms: int) -> None:
        start = self._page.locator(SELECTORS["bot_start_button"]).first
        try:
            if start.is_visible(timeout=2_000):
                start.click(timeout=timeout_ms)
                self._page.wait_for_timeout(500)
                prepare_chat_layout(self._page)
        except PlaywrightTimeoutError:
            pass

    def _composer(self) -> Locator:
        return self._page.locator(SELECTORS["composer_peer"]).first

    def _dismiss_sticker_panels(self) -> None:
        """Close emoji/sticker pickers without navigating away from the chat."""
        for selector in (
            "#column-center .emoji-dropdown .btn-icon",
            "#column-center .sticker-container .btn-icon",
        ):
            close = self._page.locator(selector).first
            try:
                if close.is_visible(timeout=300):
                    close.click(timeout=1_000)
            except PlaywrightTimeoutError:
                continue

    def _focus_composer(self, *, timeout_ms: int) -> Locator:
        """Focus the message composer (reveals hidden input when the chat column is active)."""
        prepare_chat_layout(self._page)
        self._dismiss_sticker_panels()

        chat_input = self._page.locator(SELECTORS["chat_input_row"]).first
        chat_input.wait_for(state="visible", timeout=timeout_ms)
        chat_input.scroll_into_view_if_needed(timeout=timeout_ms)

        composer = self._composer()
        composer.wait_for(state="attached", timeout=timeout_ms)
        if not composer.is_visible():
            chat_input.click(timeout=timeout_ms)
            prepare_chat_layout(self._page)
        composer.wait_for(state="visible", timeout=timeout_ms)
        composer.focus(timeout=timeout_ms)
        return composer

    def _wait_for_composer(self, *, timeout_ms: int) -> None:
        prepare_chat_layout(self._page)
        composer = self._composer()
        composer.wait_for(state="visible", timeout=timeout_ms)
        self._page.locator(SELECTORS["chat_input_row"]).first.wait_for(
            state="visible",
            timeout=timeout_ms,
        )

    def send_message(self, text: str, *, timeout_ms: int = 15_000) -> None:
        """Type ``text`` into the composer and submit."""
        if not self._is_chat_active():
            self.open_bot_chat(timeout_ms=max(timeout_ms, 30_000))
        composer = self._focus_composer(timeout_ms=timeout_ms)
        composer.fill(text, timeout=timeout_ms)
        self._page.keyboard.press("Enter")
        prepare_chat_layout(self._page)

    def _is_chat_active(self) -> bool:
        if (
            f"@{self._bot_username}" not in self._page.url
            and "#" not in self._page.url.split("/k")[-1]
        ):
            return False
        try:
            return self._composer().is_visible(timeout=1_000)
        except PlaywrightTimeoutError:
            return False

    def last_message_text(self, *, timeout_ms: int = 15_000) -> str:
        """Return visible text from the newest in-chat bubble."""
        texts = self.recent_message_texts(limit=1, timeout_ms=timeout_ms)
        if texts:
            return texts[-1]
        prepare_chat_layout(self._page)
        bubble = self._message_bubbles().last
        bubble.wait_for(state="visible", timeout=timeout_ms)
        return bubble.inner_text(timeout=timeout_ms).strip()

    def recent_message_texts(self, *, limit: int = 12, timeout_ms: int = 5_000) -> list[str]:
        """Return visible text from the last ``limit`` in-chat bubbles (oldest first)."""
        prepare_chat_layout(self._page)
        bubbles = self._message_bubbles()
        count = bubbles.count()
        if not isinstance(count, int) or count <= 0:
            return []
        start = max(0, count - limit)
        texts: list[str] = []
        for index in range(start, count):
            bubble = bubbles.nth(index)
            try:
                bubble.wait_for(state="visible", timeout=timeout_ms)
                text = bubble.inner_text(timeout=timeout_ms).strip()
            except PlaywrightTimeoutError:
                continue
            if text:
                texts.append(text)
        return texts

    def wait_for_inline_keyboard(
        self,
        *,
        min_buttons: int = 1,
        label_contains: str | None = None,
        timeout_ms: int = 45_000,
        poll_ms: int = 400,
    ) -> list[str]:
        """Poll until the bottom inline keyboard has enough visible buttons.

        Args:
            min_buttons: Minimum button count required.
            label_contains: When set, at least one label must contain this substring.
            timeout_ms: Total poll budget.
            poll_ms: Delay between polls.

        Returns:
            Visible button labels from the active (bottom) keyboard.

        Raises:
            TimeoutError: When the keyboard never appears.
        """
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        last_labels: list[str] = []
        while time.monotonic() < deadline:
            last_labels = self._bottom_keyboard_labels()
            if len(last_labels) >= min_buttons and (
                label_contains is None or any(label_contains in label for label in last_labels)
            ):
                prepare_chat_layout(self._page)
                return last_labels
            time.sleep(poll_ms / 1000.0)
        msg = (
            f"timed out waiting for inline keyboard (>={min_buttons} buttons"
            f"{f', containing {label_contains!r}' if label_contains else ''}); "
            f"last={last_labels!r}"
        )
        raise TimeoutError(msg)

    def _active_keyboard_locator(self) -> Locator:
        """Locator for buttons on the newest in-chat bubble that has an inline keyboard."""
        bubbles = self._page.locator("#column-center .bubbles .bubble").filter(
            has=self._page.locator(".reply-markup-button"),
        )
        if bubbles.count() > 0:
            return bubbles.last.locator(SELECTORS["inline_button"])
        return self._page.locator(SELECTORS["inline_button"])

    def _bottom_keyboard_labels(self) -> list[str]:
        """Return all labels on the active (newest) inline keyboard in the chat column."""
        labels: list[str] = self._page.evaluate(
            """() => {
                const center = document.querySelector('#column-center');
                if (!center) return [];
                const bubbles = center.querySelectorAll('.bubbles .bubble');
                for (let i = bubbles.length - 1; i >= 0; i--) {
                    const btns = bubbles[i].querySelectorAll('.reply-markup-button');
                    if (btns.length) {
                        return Array.from(btns)
                            .map((btn) => (btn.textContent || '').trim())
                            .filter((text) => text.length > 0);
                    }
                }
                const markups = center.querySelectorAll('.reply-markup');
                if (!markups.length) return [];
                const active = markups[markups.length - 1];
                return Array.from(active.querySelectorAll('.reply-markup-button'))
                    .map((btn) => (btn.textContent || '').trim())
                    .filter((text) => text.length > 0);
            }"""
        )
        if isinstance(labels, list):
            return [str(item).strip() for item in labels if str(item).strip()]
        return []

    def click_inline_button(self, label: str, *, timeout_ms: int = 15_000) -> None:
        """Press a visible button on the active (bottom) inline keyboard."""
        prepare_chat_layout(self._page)
        pattern = re.compile(re.escape(label))
        candidates = self._active_keyboard_locator().filter(has_text=pattern)
        if candidates.count() == 0:
            candidates = self._page.locator(SELECTORS["inline_button"]).filter(has_text=pattern)
        if candidates.count() == 0:
            candidates = self._page.get_by_role("button", name=pattern)
        visible = [
            candidates.nth(index)
            for index in range(candidates.count())
            if candidates.nth(index).is_visible()
        ]
        if not visible:
            msg = f"inline button {label!r} not visible on active keyboard"
            raise TimeoutError(msg)
        btn = visible[-1]
        btn.scroll_into_view_if_needed(timeout=timeout_ms)
        btn.click(timeout=timeout_ms)
        prepare_chat_layout(self._page)
        self._page.wait_for_timeout(400)

    def inline_button_labels(self, *, timeout_ms: int = 10_000) -> list[str]:
        """Return captions on the active (bottom) inline keyboard."""
        try:
            return self.wait_for_inline_keyboard(
                min_buttons=1,
                timeout_ms=timeout_ms,
            )
        except TimeoutError:
            return self._bottom_keyboard_labels()

    def wait_for_message_matching(
        self,
        pattern: str | re.Pattern[str],
        *,
        timeout_ms: int = 60_000,
        poll_ms: int = 500,
    ) -> str:
        """Poll the latest bubble until ``pattern`` matches."""
        compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        last_text = ""
        while time.monotonic() < deadline:
            for text in reversed(self.recent_message_texts(timeout_ms=min(poll_ms, timeout_ms))):
                if compiled.search(text):
                    return text
                last_text = text
            if not last_text:
                last_text = self.last_message_text(timeout_ms=min(poll_ms, timeout_ms))
            time.sleep(poll_ms / 1000.0)
        msg = f"timed out waiting for message matching {pattern!r}; last={last_text!r}"
        raise TimeoutError(msg)

    def send_and_wait(
        self,
        text: str,
        pattern: str | re.Pattern[str],
        *,
        send_timeout_ms: int = 15_000,
        wait_timeout_ms: int = 60_000,
    ) -> str:
        """Send ``text`` and wait until the latest reply matches ``pattern``."""
        self.send_message(text, timeout_ms=send_timeout_ms)
        return self.wait_for_message_matching(pattern, timeout_ms=wait_timeout_ms)

    def _message_bubbles(self) -> Locator:
        return self._page.locator(SELECTORS["chat_bubbles"])
