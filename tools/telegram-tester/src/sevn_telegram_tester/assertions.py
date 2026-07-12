"""Test assertions for Telegram Web K E2E flows.

Module: sevn_telegram_tester.assertions
Depends: sevn_telegram_tester.telegram_client

Exports:
    assert_message_contains — substring match on the latest bubble.
    assert_inline_button_visible — keyboard button visibility probe.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sevn_telegram_tester.telegram_client import SELECTORS, TelegramClient

if TYPE_CHECKING:
    from playwright.sync_api import Page


class TelegramAssertionError(AssertionError):
    """Raised when a Telegram UI expectation is not met."""


def assert_message_contains(
    client: TelegramClient,
    needle: str,
    *,
    timeout_ms: int = 30_000,
) -> str:
    """Assert the latest message bubble includes ``needle``.

    Args:
        client: Bound Telegram client.
        needle: Expected substring.
        timeout_ms: Poll budget passed to ``last_message_text``.

    Returns:
        The observed message text.

    Raises:
        TelegramAssertionError: When the substring is absent.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> page = MagicMock()
        >>> page.locator.return_value.last.inner_text.return_value = "Deployment id: abc"
        >>> client = TelegramClient(page, bot_username="b")
        >>> assert_message_contains(client, "Deployment id", timeout_ms=1)
        'Deployment id: abc'
    """
    text = client.last_message_text(timeout_ms=timeout_ms)
    if needle not in text:
        msg = f"expected message to contain {needle!r}, got {text!r}"
        raise TelegramAssertionError(msg)
    return text


def assert_inline_button_visible(
    page: Page,
    label: str,
    *,
    timeout_ms: int = 10_000,
) -> None:
    """Assert an inline keyboard button with ``label`` is visible.

    Args:
        page: Active Telegram Web page.
        label: Button caption.
        timeout_ms: Maximum wait.

    Raises:
        TelegramAssertionError: When the button is not visible.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> page = MagicMock()
        >>> page.locator.return_value.filter.return_value.first.is_visible.return_value = True
        >>> assert_inline_button_visible(page, "Menu", timeout_ms=1)
    """
    visible = (
        page.locator(SELECTORS["inline_button"])
        .filter(has_text=label)
        .first.is_visible(timeout=timeout_ms)
    )
    if not visible:
        msg = f"expected inline button {label!r} to be visible"
        raise TelegramAssertionError(msg)
