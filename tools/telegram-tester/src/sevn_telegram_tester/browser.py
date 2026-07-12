"""Playwright browser lifecycle for Telegram Web K.

Module: sevn_telegram_tester.browser
Depends: playwright.sync_api, loguru

Exports:
    BrowserSession — persistent Chromium context for Telegram Web.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Page, Playwright

    from sevn_telegram_tester.config import TelegramTesterSettings


class BrowserSession:
    """Owns a headed or headless Chromium profile for Telegram Web."""

    def __init__(self, settings: TelegramTesterSettings) -> None:
        self._settings = settings
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None

    @contextmanager
    def open(self) -> Iterator[Page]:
        """Launch Chromium with a persistent profile and yield the active page.

        Yields:
            Playwright page positioned on Telegram Web K.

        Examples:
            >>> from pathlib import Path
            >>> from sevn_telegram_tester.config import TelegramTesterSettings
            >>> from sevn_telegram_tester.browser import BrowserSession
            >>> settings = TelegramTesterSettings(
            ...     browser_profile_dir=Path("/tmp/sevn-tg-profile"),
            ...     headless=True,
            ... )
            >>> session = BrowserSession(settings)
            >>> session._settings.headless
            True
        """
        from playwright.sync_api import sync_playwright

        from sevn_telegram_tester.auth import wait_for_main_ui
        from sevn_telegram_tester.page_setup import prepare_telegram_page

        self._settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        self._settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
        width = self._settings.browser_viewport_width
        height = self._settings.browser_viewport_height
        scale = self._settings.browser_device_scale_factor
        headed = not self._settings.headless
        logger.info(
            "launching chromium profile={profile} headless={headless} viewport={w}x{h} scale={scale} headed_fit={headed}",
            profile=self._settings.browser_profile_dir,
            headless=self._settings.headless,
            w=width,
            h=height,
            scale=scale,
            headed=headed,
        )
        launch_args = [
            f"--force-device-scale-factor={scale}",
            "--disable-features=TranslateUI",
        ]
        if headed:
            launch_args.append("--start-maximized")
        else:
            launch_args.insert(0, f"--window-size={width},{height}")
        launch_kwargs: dict[str, object] = {
            "user_data_dir": str(self._settings.browser_profile_dir),
            "headless": self._settings.headless,
            "args": launch_args,
            "locale": "en-US",
        }
        if headed:
            # Playwright forbids device_scale_factor with no_viewport; use launch arg instead.
            launch_kwargs["no_viewport"] = True
        else:
            launch_kwargs["viewport"] = {"width": width, "height": height}
            launch_kwargs["device_scale_factor"] = scale
        if self._settings.browser_channel:
            launch_kwargs["channel"] = self._settings.browser_channel
            logger.info("using Playwright browser channel={}", self._settings.browser_channel)
        with sync_playwright() as playwright:
            self._playwright = playwright
            self._context = playwright.chromium.launch_persistent_context(**launch_kwargs)
            page = self._context.pages[0] if self._context.pages else self._context.new_page()
            page.goto(self._settings.telegram_web_url, wait_until="domcontentloaded")
            try:
                wait_for_main_ui(page, timeout_ms=90_000)
            except TimeoutError:
                logger.warning(
                    "Telegram Web main UI not visible yet (QR login or slow load); continuing"
                )
            prepare_telegram_page(page, self._settings)
            try:
                yield page
            finally:
                self._context.close()
                self._playwright = None
                self._context = None

    def context(self) -> BrowserContext | None:
        """Return the active Playwright browser context, if any."""
        return self._context

    def playwright(self) -> Any:
        """Return the underlying Playwright handle for advanced callers."""
        return self._playwright
