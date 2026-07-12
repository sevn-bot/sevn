"""System Chrome browser automation for the onboarding wizard (D3).

Attaches to operator Chrome via CDP or launches headed system Chrome with an
operator-chosen ``user-data-dir``. Used by Telegram Web / BotFather flows (W5).

Module: sevn.onboarding.browser_automation
Depends: asyncio, atexit, os, subprocess, time, sevn.skills.browser_session

Exports:
    BrowserSession — shared onboarding browser contract (implemented by CDP engine).
    BrowserStartRequest — resolved attach/launch inputs for :meth:`BrowserSession.start`.
    get_browser_session — process-wide singleton session for wizard API routes.
    register_shutdown_hooks — ``atexit`` + lifespan companion for teardown.
    reset_browser_session_for_tests — clear singleton state (unit tests only).
    resolve_start_request — merge API body, env, and defaults for browser start.
    stop_browser_on_shutdown — idempotent shutdown helper for FastAPI lifespan.

Examples:
    >>> from sevn.onboarding.browser_automation import resolve_start_request
    >>> req = resolve_start_request()
    >>> req.user_data_dir.endswith("onboarding-chrome-profile")
    True
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import os
import subprocess  # nosec B404
import time
from dataclasses import dataclass
from typing import Any

from sevn.skills.browser_session import cdp_reachable

_ONBOARD_PROFILE_ENV = "SEVN_ONBOARD_BROWSER_PROFILE_DIR"
_SESSION: BrowserSession | None = None
_SHUTDOWN_REGISTERED = False


@dataclass(frozen=True, slots=True)
class BrowserStartRequest:
    """Resolved inputs for :meth:`BrowserSession.start`."""

    cdp_url: str | None
    user_data_dir: str | None


def _default_onboard_profile_dir() -> str:
    """Return the default Chrome profile directory for onboarding automation.

    Returns:
        str: Absolute profile path under operator home.

    Examples:
        >>> _default_onboard_profile_dir().endswith("onboarding-chrome-profile")
        True
    """
    from sevn.cli.workspace import sevn_home_dir

    return str((sevn_home_dir() / "onboarding-chrome-profile").resolve())


def resolve_start_request(
    *,
    cdp_url: str | None = None,
    user_data_dir: str | None = None,
) -> BrowserStartRequest:
    """Merge API body, env, and defaults for browser start.

    Args:
        cdp_url (str | None): Explicit CDP base URL from the wizard API.
        user_data_dir (str | None): Chrome profile directory for launch mode.

    Returns:
        BrowserStartRequest: Normalised attach/launch inputs.

    Examples:
        >>> req = resolve_start_request(user_data_dir="/tmp/p")
        >>> req.user_data_dir.endswith("p")
        True
    """
    from sevn.skills.browser_session import default_cdp_url

    url = (cdp_url or default_cdp_url() or "").strip() or None
    profile = (user_data_dir or os.environ.get(_ONBOARD_PROFILE_ENV, "").strip() or "").strip()
    if not profile:
        profile = _default_onboard_profile_dir()
    return BrowserStartRequest(cdp_url=url, user_data_dir=profile)


class BrowserSession:
    """Onboarding wizard browser session — system Chrome via native CDP (D3).

    Supports CDP attach to an already-running Chrome instance or headed launch with
    ``--user-data-dir``. Concrete automation lives in :class:`~sevn.onboarding.cdp_browser.CDPOnboardingBrowser`.
    """

    def __init__(self) -> None:
        """Initialise an idle session (call :meth:`start` before automation).

        Returns:
            None

        Examples:
            >>> isinstance(BrowserSession(), BrowserSession)
            True
        """
        self._lock = asyncio.Lock()
        self._chrome_proc: subprocess.Popen[bytes] | None = None
        self._spawned_chrome = False
        self._cdp_url: str | None = None
        self._profile_dir: str | None = None
        self._active_target_id: str | None = None
        self._steps: list[dict[str, Any]] = []
        self._running = False

    @property
    def running(self) -> bool:
        """Return whether a browser session is active.

        Returns:
            bool: ``True`` after successful :meth:`start` until :meth:`stop`.

        Examples:
            >>> BrowserSession().running
            False
        """
        return self._running

    def _record_step(self, label: str, *, state: str = "done") -> None:
        """Append a poll-visible automation step label (no credentials).

        Args:
            label (str): Human-readable step name for ``GET /api/browser/status``.
            state (str): ``running`` or ``done``.

        Returns:
            None

        Examples:
            >>> s = BrowserSession()
            >>> s._record_step("browser.ready")
            >>> s._steps[-1]["label"]
            'browser.ready'
        """
        self._steps.append({"label": label, "state": state, "ts": time.time()})

    async def _await_cdp_ready(self, cdp_url: str, *, wait_seconds: float = 15.0) -> None:
        """Poll until the freshly spawned Chrome CDP endpoint accepts connections.

        Args:
            cdp_url (str): CDP base URL of the spawned Chrome.
            wait_seconds (float): Maximum seconds to poll for readiness.

        Returns:
            None

        Raises:
            RuntimeError: When the endpoint is not reachable before the deadline.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserSession._await_cdp_ready)
            True
        """
        deadline = time.monotonic() + max(0.5, wait_seconds)
        while time.monotonic() < deadline:
            if await asyncio.to_thread(cdp_reachable, cdp_url):
                return
            await asyncio.sleep(0.25)
        msg = f"CDP endpoint not reachable after launch: {cdp_url}"
        raise RuntimeError(msg)

    async def start(
        self,
        *,
        cdp_url: str | None = None,
        user_data_dir: str | None = None,
    ) -> dict[str, Any]:
        """Start the browser session (implemented by CDP backend).

        Args:
            cdp_url (str | None): CDP base URL for attach mode.
            user_data_dir (str | None): Chrome profile for launch mode.

        Returns:
            dict[str, Any]: Status snapshot after start.

        Raises:
            NotImplementedError: When called on the abstract base class.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserSession.start)
            True
        """
        msg = "BrowserSession.start is implemented by CDPOnboardingBrowser"
        raise NotImplementedError(msg)

    async def stop(self) -> dict[str, Any]:
        """Stop the browser session (implemented by CDP backend).

        Returns:
            dict[str, Any]: Final status payload.

        Raises:
            NotImplementedError: When called on the abstract base class.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserSession.stop)
            True
        """
        msg = "BrowserSession.stop is implemented by CDPOnboardingBrowser"
        raise NotImplementedError(msg)

    def status_payload(self) -> dict[str, Any]:
        """Return poll-friendly status for ``GET /api/browser/status``.

        Returns:
            dict[str, Any]: Running flag, CDP URL, profile dir, steps, tab count.

        Examples:
            >>> payload = BrowserSession().status_payload()
            >>> payload["running"] is False and "steps" in payload
            True
        """
        return {
            "running": self._running,
            "browser_engine": "cdp",
            "cdp_url": self._cdp_url,
            "user_data_dir": self._profile_dir,
            "spawned_chrome": self._spawned_chrome,
            "active_target_id": self._active_target_id,
            "tab_count": 0,
            "steps": list(self._steps),
        }

    def _resolve_tab(self, tab_id: str | None = None) -> Any:
        """Resolve explicit or active tab for an automation call (CDP backend).

        Args:
            tab_id (str | None): CDP target id; active tab when omitted.

        Returns:
            Any: Tab shim instance.

        Raises:
            NotImplementedError: When called on the abstract base class.

        Examples:
            >>> s = BrowserSession()
            >>> try:
            ...     s._resolve_tab()
            ... except NotImplementedError:
            ...     True
            True
        """
        _ = tab_id
        msg = "BrowserSession._resolve_tab is implemented by CDPOnboardingBrowser"
        raise NotImplementedError(msg)

    async def open_url(self, url: str, *, tab_id: str | None = None) -> dict[str, Any]:
        """Navigate a tab to ``url`` (implemented by CDP backend).

        Args:
            url (str): Destination URL.
            tab_id (str | None): Optional CDP target id.

        Returns:
            dict[str, Any]: Tab info row after navigation.

        Raises:
            NotImplementedError: When called on the abstract base class.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserSession.open_url)
            True
        """
        _ = url, tab_id
        msg = "BrowserSession.open_url is implemented by CDPOnboardingBrowser"
        raise NotImplementedError(msg)

    async def wait_for_selector(
        self,
        selector: str,
        *,
        wait_seconds: float = 30.0,
        tab_id: str | None = None,
    ) -> dict[str, Any]:
        """Wait until ``selector`` matches an element (implemented by CDP backend).

        Args:
            selector (str): CSS selector.
            wait_seconds (float): Maximum wait in seconds.
            tab_id (str | None): Optional tab target id.

        Returns:
            dict[str, Any]: ``{"selector": ..., "found": True}`` on success.

        Raises:
            NotImplementedError: When called on the abstract base class.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserSession.wait_for_selector)
            True
        """
        _ = selector, wait_seconds, tab_id
        msg = "BrowserSession.wait_for_selector is implemented by CDPOnboardingBrowser"
        raise NotImplementedError(msg)

    async def extract_text(
        self,
        *,
        tab_id: str | None = None,
        selector: str | None = None,
        max_chars: int = 8000,
    ) -> str:
        """Return visible text from a tab (implemented by CDP backend).

        Args:
            tab_id (str | None): Optional tab target id.
            selector (str | None): Optional CSS selector scope.
            max_chars (int): Truncate output to this length.

        Returns:
            str: Extracted text.

        Raises:
            NotImplementedError: When called on the abstract base class.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserSession.extract_text)
            True
        """
        _ = tab_id, selector, max_chars
        msg = "BrowserSession.extract_text is implemented by CDPOnboardingBrowser"
        raise NotImplementedError(msg)

    def list_tabs(self) -> list[dict[str, object]]:
        """List open tabs (implemented by CDP backend).

        Returns:
            list[dict[str, object]]: Tab rows for the wizard UI.

        Raises:
            NotImplementedError: When called on the abstract base class.

        Examples:
            >>> try:
            ...     BrowserSession().list_tabs()
            ... except NotImplementedError:
            ...     True
            True
        """
        msg = "BrowserSession.list_tabs is implemented by CDPOnboardingBrowser"
        raise NotImplementedError(msg)

    async def new_tab(self, url: str | None = None) -> dict[str, Any]:
        """Open a new tab (implemented by CDP backend).

        Args:
            url (str | None): Optional initial URL.

        Returns:
            dict[str, Any]: New tab info row.

        Raises:
            NotImplementedError: When called on the abstract base class.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserSession.new_tab)
            True
        """
        _ = url
        msg = "BrowserSession.new_tab is implemented by CDPOnboardingBrowser"
        raise NotImplementedError(msg)

    async def press_enter(self) -> None:
        """Dispatch Enter keyDown/keyUp on the active page (implemented by CDP backend).

        Returns:
            None

        Raises:
            NotImplementedError: When called on the abstract base class.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BrowserSession.press_enter)
            True
        """
        msg = "BrowserSession.press_enter is implemented by CDPOnboardingBrowser"
        raise NotImplementedError(msg)

    async def __aenter__(self) -> BrowserSession:
        """Start the session on context entry.

        Returns:
            BrowserSession: Started session.

        Examples:
            >>> import inspect
            >>> hasattr(BrowserSession, "__aenter__")
            True
        """
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Stop the session on context exit.

        Args:
            _exc (object): Exception info from the ``with`` block (ignored).

        Returns:
            None

        Examples:
            >>> import inspect
            >>> hasattr(BrowserSession, "__aexit__")
            True
        """
        await self.stop()


def get_browser_session() -> BrowserSession:
    """Return the process-wide onboarding browser session singleton.

    Returns:
        BrowserSession: Shared CDP-backed wizard session instance.

    Examples:
        >>> from sevn.onboarding.cdp_browser import CDPOnboardingBrowser
        >>> s1 = get_browser_session()
        >>> s2 = get_browser_session()
        >>> s1 is s2 and isinstance(s1, CDPOnboardingBrowser)
        True
    """
    global _SESSION
    if _SESSION is None:
        from sevn.onboarding.cdp_browser import CDPOnboardingBrowser

        _SESSION = CDPOnboardingBrowser()
    return _SESSION


async def stop_browser_on_shutdown() -> None:
    """Idempotent shutdown helper for FastAPI lifespan.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(stop_browser_on_shutdown)
        True
    """
    await get_browser_session().stop()


def _atexit_stop_browser() -> None:
    """Best-effort sync stop when lifespan did not run.

    Returns:
        None

    Examples:
        >>> _atexit_stop_browser()
        >>> True
        True
    """
    session = _SESSION
    if session is None or not session.running:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        return
    with contextlib.suppress(Exception):
        asyncio.run(session.stop())


def register_shutdown_hooks() -> None:
    """Register ``atexit`` handler once per process.

    Returns:
        None

    Examples:
        >>> register_shutdown_hooks()
        >>> True
        True
    """
    global _SHUTDOWN_REGISTERED
    if _SHUTDOWN_REGISTERED:
        return
    atexit.register(_atexit_stop_browser)
    _SHUTDOWN_REGISTERED = True


def reset_browser_session_for_tests() -> None:
    """Clear the module singleton (unit tests only).

    Returns:
        None

    Examples:
        >>> reset_browser_session_for_tests()
        >>> True
        True
    """
    global _SESSION
    _SESSION = None


__all__ = [
    "BrowserSession",
    "get_browser_session",
    "register_shutdown_hooks",
    "reset_browser_session_for_tests",
    "resolve_start_request",
    "stop_browser_on_shutdown",
]
