"""Unit tests for ``TelegramClient`` with mocked Playwright."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sevn_telegram_tester.telegram_client import SELECTORS, TelegramClient


def _chainable_locator() -> MagicMock:
    loc = MagicMock()
    loc.first = loc
    loc.last = loc
    loc.nth.return_value = loc
    loc.filter.return_value = loc
    loc.click.return_value = None
    loc.fill.return_value = None
    loc.wait_for.return_value = None
    loc.scroll_into_view_if_needed.return_value = None
    loc.inner_text.return_value = "hello"
    loc.is_visible.return_value = True
    loc.count.return_value = 1
    return loc


def test_selectors_exposes_core_hooks() -> None:
    assert "composer_peer" in SELECTORS
    assert "bubble-content" in SELECTORS["chat_bubbles"]


def test_open_config_waits_for_keyboard() -> None:
    client = MagicMock()
    client.wait_for_inline_keyboard.return_value = ["❓ Help", "❌ Close"]
    from sevn_telegram_tester.suites.session import _CONFIG_ROOT_MIN_BUTTONS, _open_config

    labels = _open_config(client)
    assert "Help" in labels[0]
    client.send_message.assert_called_once_with("/config")
    client.wait_for_inline_keyboard.assert_called_once_with(
        min_buttons=_CONFIG_ROOT_MIN_BUTTONS,
        label_contains="Help",
        timeout_ms=45_000,
    )


def test_active_keyboard_locator_prefers_last_bubble() -> None:
    page = MagicMock()
    scoped = MagicMock()
    bubble_last = MagicMock()
    bubble_last.locator.return_value = scoped
    filtered = MagicMock()
    filtered.count.return_value = 1
    filtered.last = bubble_last
    bubbles = MagicMock()
    bubbles.filter.return_value = filtered
    markup_btn = MagicMock()

    def _locator(sel: str) -> MagicMock:
        if ".bubbles .bubble" in sel:
            return bubbles
        if ".reply-markup-button" in sel:
            return markup_btn
        return MagicMock()

    page.locator.side_effect = _locator
    client = TelegramClient(page, bot_username="b")
    assert client._active_keyboard_locator() is scoped
    bubble_last.locator.assert_called_once_with(SELECTORS["inline_button"])


def test_send_message_fills_composer() -> None:
    page = MagicMock()
    page.url = "https://web.telegram.org/k/#@b"
    locator = _chainable_locator()
    page.locator.return_value = locator
    client = TelegramClient(page, bot_username="b")
    with patch.object(client, "_is_chat_active", return_value=True):
        client.send_message("/status", timeout_ms=1)
    locator.focus.assert_called()
    locator.fill.assert_called_with("/status", timeout=1)
