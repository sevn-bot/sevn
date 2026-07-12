"""Telegram Web login detection for the Playwright harness.

Module: sevn_telegram_tester.auth
Depends: playwright.sync_api

Exports:
    is_logged_in — whether the session shows the main chat UI.
    wait_for_login — block until QR login completes (headed ``login`` flow).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sevn_telegram_tester.telegram_client import SELECTORS

if TYPE_CHECKING:
    from playwright.sync_api import Page


def is_logged_in(page: Page, *, timeout_ms: int = 3_000) -> bool:
    """Return True when the chat list or composer is visible (not the QR gate).

    Args:
        page: Active Telegram Web page.
        timeout_ms: Maximum wait per probe selector.

    Returns:
        True when logged in.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> page = MagicMock()
        >>> page.locator.return_value.first.is_visible.return_value = True
        >>> is_logged_in(page, timeout_ms=1)
        True
    """
    probes = (
        SELECTORS["chat_list"],
        SELECTORS["chat_input_row"],
        SELECTORS["left_column"],
    )
    for selector in probes:
        if page.locator(selector).first.is_visible(timeout=timeout_ms):
            return True
    return page.locator(SELECTORS["qr_login"]).count() == 0


def wait_for_main_ui(page: Page, *, timeout_ms: int = 60_000) -> None:
    """Wait until the logged-in Telegram Web K shell is visible.

    Args:
        page: Active Telegram Web page.
        timeout_ms: Maximum wait in milliseconds.

    Raises:
        TimeoutError: When neither chat list nor composer appears.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> page = MagicMock()
        >>> page.locator.return_value.first.wait_for.return_value = None
        >>> wait_for_main_ui(page, timeout_ms=1)  # doctest: +ELLIPSIS
    """
    combined = f"{SELECTORS['chat_list']}, {SELECTORS['chat_input_row']}"
    page.locator(combined).first.wait_for(state="visible", timeout=timeout_ms)


def wait_for_login(page: Page, *, timeout_ms: int = 300_000) -> None:
    """Wait until QR login completes and the main UI is visible.

    Args:
        page: Active Telegram Web page opened in headed mode.
        timeout_ms: Maximum wait in milliseconds.

    Raises:
        TimeoutError: When login does not complete in time.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> page = MagicMock()
        >>> page.locator.return_value.first.wait_for.return_value = None
        >>> wait_for_login(page, timeout_ms=1)  # doctest: +ELLIPSIS
    """
    wait_for_main_ui(page, timeout_ms=timeout_ms)
