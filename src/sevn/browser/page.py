"""Page primitives over a CDP page session: navigate, wait, extract, screenshot.

A :class:`Page` wraps a :class:`~sevn.browser.cdp.session.CDPSession` bound to one page
target and provides the everyday automation surface: navigation with load waiting,
JavaScript evaluation, text/HTML extraction, ``wait_for`` polling, screenshots,
cookies, and JavaScript-dialog handling. Element interaction lives in
:mod:`sevn.browser.element`.

Module: sevn.browser.page
Depends: asyncio, base64, contextlib, pathlib, time, sevn.browser.cdp

Exports:
    Page — high-level page automation over one CDP page session.
    PageError — navigation/evaluation failure raised by :class:`Page`.

Examples:
    >>> import inspect
    >>> inspect.iscoroutinefunction(Page.goto)
    True
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import time
from typing import TYPE_CHECKING, Any, Final

from sevn.browser.cdp import CDPError

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.browser.cdp import CDPSession

_DEFAULT_NAV_TIMEOUT: Final[float] = 30.0
_DEFAULT_WAIT_TIMEOUT: Final[float] = 15.0
_WAIT_POLL_INTERVAL: Final[float] = 0.2


def _write_png(path: Path, data: bytes) -> None:
    """Write screenshot ``data`` to ``path`` (blocking; called via ``to_thread``).

    Args:
        path (Path): Destination PNG path (parents created).
        data (bytes): Decoded PNG bytes.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_write_png)
        True
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class PageError(RuntimeError):
    """A page navigation or JavaScript evaluation failed."""


class Page:
    """Everyday page automation over one attached CDP page session."""

    def __init__(self, session: CDPSession) -> None:
        """Bind a page-target CDP session.

        Args:
            session (CDPSession): Session bound to a page ``targetId``.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(Page.__init__)
            True
        """
        self._session = session

    @property
    def session(self) -> CDPSession:
        """Return the underlying page CDP session.

        Returns:
            CDPSession: The bound page session.

        Examples:
            >>> import inspect
            >>> isinstance(Page.session, property)
            True
        """
        return self._session

    async def _ensure_domains(self) -> None:
        """Enable the Page/DOM/Runtime/Network domains once for this session.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Page._ensure_domains)
            True
        """
        for domain in ("Page", "Runtime", "DOM"):
            with contextlib.suppress(CDPError):
                await self._session.enable(domain)

    async def goto(
        self,
        url: str,
        *,
        wait_until: str = "load",
        timeout: float = _DEFAULT_NAV_TIMEOUT,
    ) -> dict[str, Any]:
        """Navigate to ``url`` and wait for the requested lifecycle state.

        Args:
            url (str): Destination URL.
            wait_until (str): ``load`` (default) or ``none`` to skip waiting.
            timeout (float): Seconds to await the load event.

        Returns:
            dict[str, Any]: ``{url, frame_id}`` after navigation.

        Raises:
            PageError: When Chrome reports a navigation error.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Page.goto)
            True
        """
        await self._ensure_domains()
        try:
            result = await self._session.send("Page.navigate", {"url": url}, timeout=timeout)
        except CDPError as exc:
            raise PageError(f"navigate failed: {exc}") from exc
        if result.get("errorText"):
            msg = f"navigation error: {result.get('errorText')}"
            raise PageError(msg)
        if wait_until == "load":
            with contextlib.suppress(TimeoutError):
                await self._session.wait_for("Page.loadEventFired", timeout=timeout)
        return {"url": url, "frame_id": result.get("frameId")}

    async def reload(self, *, timeout: float = _DEFAULT_NAV_TIMEOUT) -> None:
        """Reload the current page and wait for load.

        Args:
            timeout (float): Seconds to await the load event.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Page.reload)
            True
        """
        await self._ensure_domains()
        await self._session.send("Page.reload", {})
        with contextlib.suppress(TimeoutError):
            await self._session.wait_for("Page.loadEventFired", timeout=timeout)

    async def _history_go(self, delta: int, *, timeout: float) -> bool:
        """Navigate the history by ``delta`` entries (negative ⇒ back).

        Args:
            delta (int): Offset from the current history index.
            timeout (float): Seconds to await the load event.

        Returns:
            bool: ``True`` when a target entry existed and navigation was issued.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Page._history_go)
            True
        """
        await self._ensure_domains()
        history = await self._session.send("Page.getNavigationHistory", {})
        entries = history.get("entries") or []
        current = int(history.get("currentIndex", 0))
        target = current + delta
        if not isinstance(entries, list) or not (0 <= target < len(entries)):
            return False
        entry_id = entries[target].get("id")
        await self._session.send("Page.navigateToHistoryEntry", {"entryId": entry_id})
        with contextlib.suppress(TimeoutError):
            await self._session.wait_for("Page.loadEventFired", timeout=timeout)
        return True

    async def back(self, *, timeout: float = _DEFAULT_NAV_TIMEOUT) -> bool:
        """Go back one history entry.

        Args:
            timeout (float): Seconds to await the load event.

        Returns:
            bool: ``True`` when there was an entry to go back to.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Page.back)
            True
        """
        return await self._history_go(-1, timeout=timeout)

    async def forward(self, *, timeout: float = _DEFAULT_NAV_TIMEOUT) -> bool:
        """Go forward one history entry.

        Args:
            timeout (float): Seconds to await the load event.

        Returns:
            bool: ``True`` when there was an entry to go forward to.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Page.forward)
            True
        """
        return await self._history_go(1, timeout=timeout)

    async def evaluate(self, expression: str, *, return_by_value: bool = True) -> Any:
        """Evaluate a JavaScript ``expression`` in the page and return its value.

        Args:
            expression (str): JavaScript source to evaluate.
            return_by_value (bool): Return the JSON value (default) vs a remote handle.

        Returns:
            Any: The evaluated value (when ``return_by_value``), else the raw result.

        Raises:
            PageError: When the script throws.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Page.evaluate)
            True
        """
        await self._ensure_domains()
        result = await self._session.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": return_by_value,
                "awaitPromise": True,
            },
        )
        details = result.get("exceptionDetails")
        if details:
            text = details.get("text") or "evaluation error"
            exc = details.get("exception") or {}
            desc = exc.get("description") or exc.get("value") or ""
            raise PageError(f"{text}: {desc}".strip(": "))
        remote = result.get("result") or {}
        return remote.get("value") if return_by_value else remote

    async def url(self) -> str:
        """Return the current document URL.

        Returns:
            str: ``document.location.href`` or empty string.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Page.url)
            True
        """
        with contextlib.suppress(PageError, CDPError):
            return str(await self.evaluate("document.location.href") or "")
        return ""

    async def title(self) -> str:
        """Return the document title.

        Returns:
            str: ``document.title`` or empty string.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Page.title)
            True
        """
        with contextlib.suppress(PageError, CDPError):
            return str(await self.evaluate("document.title") or "")
        return ""

    async def extract_text(self, *, selector: str | None = None, max_chars: int = 8000) -> str:
        """Return visible text from the page or a selector scope (capped).

        Args:
            selector (str | None): CSS selector to scope extraction; whole body when ``None``.
            max_chars (int): Maximum characters to return.

        Returns:
            str: Visible ``innerText`` (trimmed, capped).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Page.extract_text)
            True
        """
        if selector:
            expr = (
                "(() => { const el = document.querySelector("
                f"{selector!r}); return el ? el.innerText : ''; }})()"
            )
        else:
            expr = "(document.body && document.body.innerText) || ''"
        text = str(await self.evaluate(expr) or "").strip()
        return text[:max_chars]

    async def extract_html(self, *, selector: str | None = None, max_chars: int = 32000) -> str:
        """Return outer HTML for the document or a selector scope (capped).

        Args:
            selector (str | None): CSS selector to scope extraction; whole document when ``None``.
            max_chars (int): Maximum characters to return.

        Returns:
            str: Outer HTML (capped).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Page.extract_html)
            True
        """
        if selector:
            expr = (
                "(() => { const el = document.querySelector("
                f"{selector!r}); return el ? el.outerHTML : ''; }})()"
            )
        else:
            expr = "document.documentElement.outerHTML"
        html = str(await self.evaluate(expr) or "")
        return html[:max_chars]

    async def page_state(self) -> dict[str, object]:
        """Return ``url``, ``title``, and a short text excerpt for the page.

        Returns:
            dict[str, object]: ``{url, title, text_excerpt, has_content}``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Page.page_state)
            True
        """
        text = await self.extract_text(max_chars=600)
        return {
            "url": await self.url(),
            "title": await self.title(),
            "text_excerpt": text[:500],
            "has_content": bool(text),
        }

    async def wait_for(
        self,
        selector: str,
        *,
        timeout: float = _DEFAULT_WAIT_TIMEOUT,
        visible: bool = False,
    ) -> bool:
        """Poll until ``selector`` matches (optionally is visible) or time out.

        Args:
            selector (str): CSS selector to await.
            timeout (float): Maximum seconds to poll.
            visible (bool): Require a non-zero client rect when ``True``.

        Returns:
            bool: ``True`` when the selector appeared in time.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Page.wait_for)
            True
        """
        if visible:
            expr = (
                "(() => { const el = document.querySelector("
                f"{selector!r}); if (!el) return false; const r = el.getClientRects();"
                " return r.length > 0 && r[0].width > 0 && r[0].height > 0; }})()"
            )
        else:
            expr = f"!!document.querySelector({selector!r})"
        deadline = time.monotonic() + max(0.1, timeout)
        while time.monotonic() < deadline:
            with contextlib.suppress(PageError, CDPError):
                if bool(await self.evaluate(expr)):
                    return True
            await asyncio.sleep(_WAIT_POLL_INTERVAL)
        return False

    async def screenshot(self, path: Path, *, full_page: bool = False) -> str:
        """Capture a PNG screenshot to ``path`` and return the absolute path.

        Args:
            path (Path): Destination ``.png`` file (parents created).
            full_page (bool): Capture the full scrollable page when ``True``.

        Returns:
            str: Absolute path to the written PNG.

        Raises:
            PageError: When Chrome returns no image data.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Page.screenshot)
            True
        """
        await self._ensure_domains()
        params: dict[str, Any] = {"format": "png", "captureBeyondViewport": full_page}
        if full_page:
            metrics = await self._session.send("Page.getLayoutMetrics", {})
            css = metrics.get("cssContentSize") or metrics.get("contentSize") or {}
            if css:
                params["clip"] = {
                    "x": 0,
                    "y": 0,
                    "width": css.get("width", 0),
                    "height": css.get("height", 0),
                    "scale": 1,
                }
        result = await self._session.send("Page.captureScreenshot", params)
        data = result.get("data")
        if not isinstance(data, str) or not data:
            msg = "captureScreenshot returned no data"
            raise PageError(msg)
        await asyncio.to_thread(_write_png, path, base64.b64decode(data))
        return str(path)

    async def get_cookies(self) -> list[dict[str, Any]]:
        """Return all cookies visible to the browser (``Network.getAllCookies``).

        Returns:
            list[dict[str, Any]]: Cookie objects.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Page.get_cookies)
            True
        """
        with contextlib.suppress(CDPError):
            await self._session.enable("Network")
        result = await self._session.send("Network.getAllCookies", {})
        cookies = result.get("cookies")
        return [c for c in cookies if isinstance(c, dict)] if isinstance(cookies, list) else []

    async def set_cookies(self, cookies: list[dict[str, Any]]) -> int:
        """Set ``cookies`` on the browser (``Network.setCookies``).

        Args:
            cookies (list[dict[str, Any]]): Cookie objects (``name``/``value``/``domain``...).

        Returns:
            int: Number of cookies submitted.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Page.set_cookies)
            True
        """
        with contextlib.suppress(CDPError):
            await self._session.enable("Network")
        await self._session.send("Network.setCookies", {"cookies": cookies})
        return len(cookies)

    async def enable_dialog_auto_handler(
        self, *, accept: bool = True, prompt_text: str = ""
    ) -> None:
        """Auto-handle JavaScript dialogs (alert/confirm/prompt/beforeunload).

        Args:
            accept (bool): Accept (``True``) or dismiss (``False``) each dialog.
            prompt_text (str): Text to supply for ``prompt`` dialogs.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Page.enable_dialog_auto_handler)
            True
        """
        await self._session.enable("Page")

        def _handle(_message: dict[str, Any]) -> Any:
            return self._session.send(
                "Page.handleJavaScriptDialog",
                {"accept": accept, "promptText": prompt_text},
            )

        self._session.on("Page.javascriptDialogOpening", _handle)


__all__ = ["Page", "PageError"]
