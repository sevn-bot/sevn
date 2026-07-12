"""Engine-backed onboarding browser — default ``BrowserSession`` implementation (W10.2).

``CDPOnboardingBrowser`` subclasses :class:`~sevn.onboarding.browser_automation.BrowserSession`
and implements its surface on the sevn-native CDP engine. It exposes a Tab-compatible shim
from ``_resolve_tab()`` so ``telegram_automation`` / ``my_telegram_automation`` run unchanged.

Module: sevn.onboarding.cdp_browser
Depends: asyncio, contextlib, os, pathlib, time, sevn.browser, sevn.onboarding.browser_automation, sevn.skills.browser_session

Exports:
    CDPOnboardingBrowser — CDP-engine onboarding browser with the BrowserSession contract.

Examples:
    >>> import inspect
    >>> inspect.iscoroutinefunction(CDPOnboardingBrowser.start)
    True
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING, Any

from sevn.onboarding.browser_automation import BrowserSession

if TYPE_CHECKING:
    from sevn.browser.element import Dom, ElementHandle
    from sevn.browser.lifecycle import CDPBrowserSession
    from sevn.browser.page import Page


class _ElementShim:
    """Element shim over a CDP :class:`ElementHandle` (onboarding automation API)."""

    def __init__(self, handle: ElementHandle) -> None:
        """Wrap a resolved element handle.

        Args:
            handle (ElementHandle): Engine element handle.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(_ElementShim.__init__)
            True
        """
        self._handle = handle

    async def click(self) -> None:
        """Click the element (synthetic mouse gesture).

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(_ElementShim.click)
            True
        """
        await self._handle.click()

    async def send_keys(self, value: str) -> None:
        """Type ``value`` into the element.

        Args:
            value (str): Text to type.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(_ElementShim.send_keys)
            True
        """
        await self._handle.type(value)

    async def clear_input(self) -> None:
        """Clear the element's current value.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(_ElementShim.clear_input)
            True
        """
        await self._handle.fill("")

    async def text_all(self) -> str:
        """Return the element's visible text.

        Returns:
            str: ``innerText`` of the element.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(_ElementShim.text_all)
            True
        """
        return await self._handle.text()


class _TabShim:
    """Tab shim over a CDP :class:`Page` + :class:`Dom` (onboarding automation API)."""

    def __init__(self, page: Page, dom: Dom) -> None:
        """Wrap a page and finder for the active onboarding tab.

        Args:
            page (Page): Engine page.
            dom (Dom): Engine finder.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(_TabShim.__init__)
            True
        """
        self._page = page
        self._dom = dom

    async def evaluate(self, expression: str, *, await_promise: bool = False) -> Any:
        """Evaluate JavaScript and return its value.

        Args:
            expression (str): JavaScript source.
            await_promise (bool): Accepted for API parity; the engine awaits promises.

        Returns:
            Any: Evaluated JSON value.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(_TabShim.evaluate)
            True
        """
        _ = await_promise
        return await self._page.evaluate(expression)

    async def select(
        self,
        selector: str,
        timeout: float = 10.0,  # noqa: ASYNC109 — onboarding Tab.select API parity
    ) -> _ElementShim | None:
        """Wait briefly for ``selector`` then return a wrapped element or ``None``.

        Args:
            selector (str): CSS selector.
            timeout (float): Seconds to wait for the selector to appear.

        Returns:
            _ElementShim | None: Wrapped element or ``None`` when not found.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(_TabShim.select)
            True
        """
        if not await self._page.wait_for(selector, timeout=timeout):
            return None
        handle = await self._dom.query(selector)
        return _ElementShim(handle) if handle is not None else None

    async def get(self, url: str) -> None:
        """Navigate the tab to ``url``.

        Args:
            url (str): Destination URL.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(_TabShim.get)
            True
        """
        await self._page.goto(url)

    async def get_content(self) -> str:
        """Return the page's outer HTML.

        Returns:
            str: Document HTML.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(_TabShim.get_content)
            True
        """
        return await self._page.extract_html()


class CDPOnboardingBrowser(BrowserSession):
    """Onboarding browser backed by the sevn-native CDP engine."""

    def __init__(self) -> None:
        """Initialise an idle CDP-engine onboarding session.

        Returns:
            None

        Examples:
            >>> CDPOnboardingBrowser().running
            False
        """
        super().__init__()
        self._engine: CDPBrowserSession | None = None
        self._page: Page | None = None
        self._dom: Dom | None = None
        self._shim: _TabShim | None = None
        self._tab_count = 0

    async def start(
        self,
        *,
        cdp_url: str | None = None,
        user_data_dir: str | None = None,
    ) -> dict[str, Any]:
        """Attach to CDP or spawn host Chrome, then bind the active page (engine).

        Args:
            cdp_url (str | None): CDP base URL for attach mode.
            user_data_dir (str | None): Chrome profile for spawn mode.

        Returns:
            dict[str, Any]: Status snapshot after start.

        Raises:
            RuntimeError: When Chrome cannot be attached or launched.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPOnboardingBrowser.start)
            True
        """
        from sevn.browser.lifecycle import CDPBrowserSession
        from sevn.onboarding.browser_automation import resolve_start_request
        from sevn.skills.browser_session import (
            cdp_reachable,
            resolve_chrome_executable,
            spawn_chrome,
        )

        async with self._lock:
            if self._running:
                return self.status_payload()
            req = resolve_start_request(cdp_url=cdp_url, user_data_dir=user_data_dir)
            self._profile_dir = req.user_data_dir
            attach_url = req.cdp_url
            if attach_url and cdp_reachable(attach_url):
                self._record_step("browser.attach", state="running")
                self._engine = await CDPBrowserSession.attach(attach_url)
                self._cdp_url = attach_url
                self._spawned_chrome = False
            else:
                if resolve_chrome_executable() is None:
                    msg = "Chrome executable not found — install system Google Chrome"
                    raise RuntimeError(msg)
                from pathlib import Path

                from sevn.onboarding.browser_automation import _default_onboard_profile_dir

                profile = Path(req.user_data_dir or _default_onboard_profile_dir())
                for stale in (
                    "DevToolsActivePort",
                    "SingletonLock",
                    "SingletonSocket",
                    "SingletonCookie",
                ):
                    with contextlib.suppress(OSError):
                        (profile / stale).unlink()
                self._record_step("browser.launch", state="running")
                proc, _port, launched_url = await asyncio.to_thread(
                    spawn_chrome, profile, headless=False
                )
                self._chrome_proc = proc
                self._cdp_url = launched_url
                self._spawned_chrome = True
                await self._await_cdp_ready(launched_url)
                self._engine = await CDPBrowserSession.attach(launched_url)
            self._steps[-1]["state"] = "done"
            await self._bind_active_tab()
            self._record_step("browser.ready")
            self._running = True
            return self.status_payload()

    async def _bind_active_tab(self, target_id: str | None = None) -> None:
        """Resolve and cache a Page/Dom shim for the active (or given) tab.

        Args:
            target_id (str | None): Explicit target id; last page target when ``None``.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPOnboardingBrowser._bind_active_tab)
            True
        """
        from sevn.browser.element import Dom
        from sevn.browser.page import Page

        if self._engine is None:
            return
        pages = await self._engine.page_targets()
        self._tab_count = len(pages)
        tid = target_id or (str(pages[-1].get("targetId")) if pages else None)
        if not tid:
            new_row = await self._engine.open_tab("about:blank")
            tid = str(new_row["target_id"])
            self._tab_count += 1
        cdp_session = await self._engine.session_for(tid)
        self._active_target_id = tid
        self._page = Page(cdp_session)
        self._dom = Dom(cdp_session)
        self._shim = _TabShim(self._page, self._dom)

    def _resolve_tab(self, tab_id: str | None = None) -> Any:
        """Return the cached active-tab shim (sync contract for automation flows).

        Args:
            tab_id (str | None): Ignored; the onboarding flows use the active tab.

        Returns:
            Any: The active :class:`_TabShim`.

        Raises:
            RuntimeError: When the session has not been started.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(CDPOnboardingBrowser._resolve_tab)
            True
        """
        _ = tab_id
        if self._shim is None or not self._running:
            msg = "browser session not started — POST /api/browser/start first"
            raise RuntimeError(msg)
        return self._shim

    async def open_url(self, url: str, *, tab_id: str | None = None) -> dict[str, Any]:
        """Navigate the active tab to ``url``.

        Args:
            url (str): Destination URL.
            tab_id (str | None): Ignored (active tab).

        Returns:
            dict[str, Any]: ``{target_id, url, title, active}``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPOnboardingBrowser.open_url)
            True
        """
        _ = tab_id
        if self._page is None:
            await self._bind_active_tab()
        if self._page is None:
            msg = "no active CDP page bound"
            raise RuntimeError(msg)
        dest = url.strip()
        self._record_step(f"open_url:{dest[:80]}")
        await self._page.goto(dest)
        return {
            "target_id": self._active_target_id or "",
            "url": await self._page.url(),
            "title": await self._page.title(),
            "active": True,
        }

    async def wait_for_selector(
        self,
        selector: str,
        *,
        wait_seconds: float = 30.0,
        tab_id: str | None = None,
    ) -> dict[str, Any]:
        """Wait until ``selector`` appears on the active tab.

        Args:
            selector (str): CSS selector.
            wait_seconds (float): Maximum wait in seconds.
            tab_id (str | None): Ignored (active tab).

        Returns:
            dict[str, Any]: ``{selector, found: True}`` on success.

        Raises:
            TimeoutError: When the selector does not appear in time.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPOnboardingBrowser.wait_for_selector)
            True
        """
        _ = tab_id
        if self._page is None:
            msg = "no active CDP page bound"
            raise RuntimeError(msg)
        needle = selector.strip()
        self._record_step(f"wait_for_selector:{needle[:60]}")
        if await self._page.wait_for(needle, timeout=wait_seconds):
            return {"selector": needle, "found": True}
        msg = f"selector not found within {wait_seconds}s: {needle!r}"
        raise TimeoutError(msg)

    async def extract_text(
        self,
        *,
        tab_id: str | None = None,
        selector: str | None = None,
        max_chars: int = 8000,
    ) -> str:
        """Return visible text from the active tab (optionally selector-scoped).

        Args:
            tab_id (str | None): Ignored (active tab).
            selector (str | None): Optional CSS selector scope.
            max_chars (int): Maximum characters to return.

        Returns:
            str: Extracted text.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPOnboardingBrowser.extract_text)
            True
        """
        _ = tab_id
        if self._page is None:
            msg = "no active CDP page bound"
            raise RuntimeError(msg)
        self._record_step("extract_text")
        return await self._page.extract_text(selector=selector, max_chars=max_chars)

    def list_tabs(self) -> list[dict[str, object]]:
        """Return the cached tab count as a single active-tab row (sync contract).

        Returns:
            list[dict[str, object]]: One-row best-effort tab list.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(CDPOnboardingBrowser.list_tabs)
            True
        """
        if not self._active_target_id:
            return []
        return [{"target_id": self._active_target_id, "url": "", "title": "", "active": True}]

    async def new_tab(self, url: str | None = None) -> dict[str, Any]:
        """Open a new tab, bind it active, and optionally navigate.

        Args:
            url (str | None): Optional initial URL.

        Returns:
            dict[str, Any]: New tab info row.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPOnboardingBrowser.new_tab)
            True
        """
        if self._engine is None:
            msg = "CDP engine session not started"
            raise RuntimeError(msg)
        dest = (url or "about:blank").strip() or "about:blank"
        self._record_step(f"new_tab:{dest[:60]}")
        row = await self._engine.open_tab(dest)
        await self._bind_active_tab(str(row["target_id"]))
        with contextlib.suppress(Exception):
            await self._engine.activate_tab(str(row["target_id"]))
        return {**row, "active": True}

    async def press_enter(self) -> None:
        """Dispatch a real Enter keyDown/keyUp on the active page (engine).

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPOnboardingBrowser.press_enter)
            True
        """
        if self._page is None:
            msg = "no active CDP page bound"
            raise RuntimeError(msg)
        spec = {
            "key": "Enter",
            "code": "Enter",
            "windowsVirtualKeyCode": 13,
            "nativeVirtualKeyCode": 13,
            "text": "\r",
        }
        for event_type in ("keyDown", "keyUp"):
            await self._page.session.send("Input.dispatchKeyEvent", {"type": event_type, **spec})

    async def stop(self) -> dict[str, Any]:
        """Disconnect the engine and terminate a wizard-spawned Chrome.

        Returns:
            dict[str, Any]: Final status payload (``running`` false).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPOnboardingBrowser.stop)
            True
        """
        import subprocess  # nosec B404 — Chrome spawn uses operator-controlled paths only

        async with self._lock:
            if not self._running and self._engine is None and self._chrome_proc is None:
                return self.status_payload()
            self._record_step("browser.stop", state="running")
            if self._engine is not None:
                await self._engine.disconnect()
                self._engine = None
            if self._spawned_chrome and self._chrome_proc is not None:
                proc = self._chrome_proc
                if proc.poll() is None:
                    proc.terminate()
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        await asyncio.to_thread(proc.wait, 8)
                self._chrome_proc = None
                self._spawned_chrome = False
            self._running = False
            self._cdp_url = None
            self._page = self._dom = self._shim = None
            self._active_target_id = None
            if self._steps and self._steps[-1]["label"] == "browser.stop":
                self._steps[-1]["state"] = "done"
            return self.status_payload()

    def status_payload(self) -> dict[str, Any]:
        """Return poll-friendly status for ``GET /api/browser/status`` (engine).

        Returns:
            dict[str, Any]: Running flag, CDP URL, profile dir, steps, tab count.

        Examples:
            >>> payload = CDPOnboardingBrowser().status_payload()
            >>> payload["browser_engine"]
            'cdp'
        """
        return {
            "running": self._running,
            "browser_engine": "cdp",
            "cdp_url": self._cdp_url,
            "user_data_dir": self._profile_dir,
            "spawned_chrome": self._spawned_chrome,
            "active_target_id": self._active_target_id,
            "tab_count": self._tab_count,
            "steps": list(self._steps),
        }

    def _record_step(self, label: str, *, state: str = "done") -> None:
        """Append a poll-visible step label (mirrors the base recorder).

        Args:
            label (str): Step name for the status payload.
            state (str): ``running`` or ``done``.

        Returns:
            None

        Examples:
            >>> s = CDPOnboardingBrowser()
            >>> s._record_step("x")
            >>> s._steps[-1]["label"]
            'x'
        """
        self._steps.append({"label": label, "state": state, "ts": time.time()})


__all__ = ["CDPOnboardingBrowser"]
