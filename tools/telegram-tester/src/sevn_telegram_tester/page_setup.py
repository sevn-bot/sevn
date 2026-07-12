"""Telegram Web K viewport and chrome normalization for Playwright.

Module: sevn_telegram_tester.page_setup
Depends: playwright.sync_api

Exports:
    prepare_telegram_page — stable window scale and left-rail promos dismissed.
    prepare_chat_layout — scroll chat column so composer and latest bubbles are in view.
    fit_browser_window — match headed window size to the physical screen.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from loguru import logger
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from sevn_telegram_tester.config import TelegramTesterSettings

# Reserve space for macOS menu bar, dock, and browser tab/chrome in headed runs.
_HEADED_CHROME_MARGIN_PX = 96
_MIN_HEADED_HEIGHT_PX = 720


def fit_browser_window(page: Page, settings: TelegramTesterSettings) -> None:
    """Size the browser window so the chat composer fits on screen.

    Headed runs use ``no_viewport`` and resize to ``screen.avail*`` so a fixed
    1080px viewport cannot extend below the laptop's visible area. Headless runs
    keep the configured viewport from settings.

    Args:
        page: Active Telegram Web page.
        settings: Browser sizing options.

    Examples:
        >>> fit_browser_window  # doctest: +SKIP
    """
    if settings.headless:
        try:
            page.set_viewport_size(
                {
                    "width": settings.browser_viewport_width,
                    "height": settings.browser_viewport_height,
                },
            )
        except PlaywrightTimeoutError:
            logger.debug("set_viewport_size skipped (headless transient state)")
        return

    dims = page.evaluate(
        """() => ({
            availW: window.screen.availWidth,
            availH: window.screen.availHeight,
            innerW: window.innerWidth,
            innerH: window.innerHeight,
        })"""
    )
    avail_w = int(dims.get("availW") or settings.browser_viewport_width)
    avail_h = int(dims.get("availH") or settings.browser_viewport_height)
    width = min(settings.browser_viewport_width, avail_w)
    height = min(
        settings.browser_viewport_height,
        max(_MIN_HEADED_HEIGHT_PX, avail_h - _HEADED_CHROME_MARGIN_PX),
    )
    try:
        page.set_viewport_size({"width": width, "height": height})
    except PlaywrightTimeoutError:
        logger.debug("set_viewport_size skipped (headed transient state)")
    logger.debug(
        "headed window fitted to {}x{} (screen avail {}x{})", width, height, avail_w, avail_h
    )


def prepare_telegram_page(page: Page, settings: TelegramTesterSettings) -> None:
    """Normalize zoom and dismiss sidebar banners that shift the chat list.

    Args:
        page: Active Telegram Web page.
        settings: Browser sizing options.

    Examples:
        >>> prepare_telegram_page  # doctest: +SKIP
    """
    fit_browser_window(page, settings)
    page.evaluate(
        """() => {
            document.body.style.zoom = '1';
            if (document.documentElement) {
                document.documentElement.style.zoom = '1';
            }
        }"""
    )
    _dismiss_left_rail_promos(page)


def prepare_chat_layout(page: Page) -> None:
    """Scroll the active chat column to the bottom and expose the composer row.

    Telegram Web K often keeps the composer in the DOM but ``visibility:hidden`` until
    the center column is active and the bubbles scroller is at the bottom. Tall inline
    keyboards can push the composer below the visible window — this routine scrolls
    bubble areas and the page until the composer row is in view.

    Args:
        page: Active Telegram Web page with an open chat.

    Examples:
        >>> prepare_chat_layout  # doctest: +SKIP
    """
    page.evaluate(
        """() => {
            const center = document.querySelector('#column-center');
            if (!center) return;
            const scrollers = center.querySelectorAll(
                '.bubbles .scrollable, .scrollable.scrollable-y'
            );
            scrollers.forEach((el) => {
                el.scrollTop = el.scrollHeight;
            });
            const composer = center.querySelector('.chat-input');
            if (!composer) return;
            const vh = window.innerHeight;
            const margin = 12;
            const rect = () => composer.getBoundingClientRect();
            let guard = 0;
            while (guard++ < 6) {
                const r = rect();
                if (r.bottom <= vh - margin && r.top >= 0) break;
                if (r.bottom > vh - margin) {
                    window.scrollBy(0, r.bottom - vh + margin);
                } else if (r.top < 0) {
                    composer.scrollIntoView({ block: 'end', behavior: 'instant' });
                }
                scrollers.forEach((el) => {
                    el.scrollTop = el.scrollHeight;
                });
            }
            const outer = center.querySelector(':scope > .scrollable.scrollable-y');
            if (outer) {
                const r = rect();
                if (r.bottom > vh - margin) {
                    outer.scrollTop += r.bottom - vh + margin;
                }
            }
        }"""
    )
    chat_input = page.locator("#column-center .chat-input").first
    with contextlib.suppress(PlaywrightTimeoutError):
        chat_input.scroll_into_view_if_needed(timeout=3_000)
    page.wait_for_timeout(150)


def _dismiss_left_rail_promos(page: Page) -> None:
    """Close birthday/update banners in the left column when present."""
    selectors = (
        "#column-left .banner .close",
        "#column-left .notification-container .close",
        "#column-left button.btn-circle.close",
    )
    for selector in selectors:
        close = page.locator(selector).first
        try:
            if close.is_visible(timeout=500):
                close.click(timeout=2_000)
                page.wait_for_timeout(300)
        except PlaywrightTimeoutError:
            continue
