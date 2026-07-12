"""Unit tests for Telegram assertion helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sevn_telegram_tester.assertions import (
    TelegramAssertionError,
    assert_inline_button_visible,
    assert_message_contains,
)
from sevn_telegram_tester.telegram_client import TelegramClient


def test_assert_message_contains_passes() -> None:
    page = MagicMock()
    locator = MagicMock()
    locator.last = locator
    locator.first = locator
    locator.wait_for.return_value = None
    locator.inner_text.return_value = "Deployment id: abc"
    page.locator.return_value = locator
    client = TelegramClient(page, bot_username="b")
    text = assert_message_contains(client, "Deployment id", timeout_ms=1)
    assert text == "Deployment id: abc"


def test_assert_message_contains_raises() -> None:
    page = MagicMock()
    locator = MagicMock()
    locator.last = locator
    locator.first = locator
    locator.wait_for.return_value = None
    locator.inner_text.return_value = "nope"
    page.locator.return_value = locator
    client = TelegramClient(page, bot_username="b")
    with pytest.raises(TelegramAssertionError, match="Deployment id"):
        assert_message_contains(client, "Deployment id", timeout_ms=1)


def test_assert_inline_button_visible_passes() -> None:
    page = MagicMock()
    locator = MagicMock()
    locator.first = locator
    locator.filter.return_value = locator
    locator.is_visible.return_value = True
    page.locator.return_value = locator
    assert_inline_button_visible(page, "Menu", timeout_ms=1)


def test_assert_inline_button_visible_raises() -> None:
    page = MagicMock()
    locator = MagicMock()
    locator.first = locator
    locator.filter.return_value = locator
    locator.is_visible.return_value = False
    page.locator.return_value = locator
    with pytest.raises(TelegramAssertionError, match="Menu"):
        assert_inline_button_visible(page, "Menu", timeout_ms=1)
