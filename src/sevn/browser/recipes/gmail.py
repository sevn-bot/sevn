"""Gmail recipe — inbox list/read/search and gated compose/reply write ops.

Read ops scrape ``mail.google.com`` inbox and message views. Write ops
(``compose``, ``reply``) require ``tools.browser.gmail.allow_write=true`` (D8).

Module: sevn.browser.recipes.gmail
Depends: asyncio, re, sevn.browser.auth, sevn.browser.page, sevn.browser.recipes.base

Exports:
    parse_inbox — parse inbox rows from saved HTML.
    parse_message — parse a message view from saved HTML.
    Gmail — live recipe over a page/dom pair.

Examples:
    >>> from sevn.browser.recipes.gmail import parse_inbox
    >>> parse_inbox("<html></html>")["count"]
    0
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any, Final

from sevn.browser.auth import login_state
from sevn.browser.recipes.base import RecipeError, require_write_allowed, validate_egress

if TYPE_CHECKING:
    from sevn.browser.element import Dom
    from sevn.browser.page import Page

GMAIL_EGRESS: Final[tuple[str, ...]] = ("mail.google.com", "google.com")
_GMAIL_URL: Final[str] = "https://mail.google.com/mail/u/0/#inbox"
_GMAIL_SEARCH_URL: Final[str] = "https://mail.google.com/mail/u/0/#search/{query}"

_INBOX_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r'<tr[^>]*class="[^"]*\bzA\b[^"]*"[^>]*>(.*?)</tr>',
    re.IGNORECASE | re.DOTALL,
)
_FROM_RE: Final[re.Pattern[str]] = re.compile(
    r'class="yX[^"]*"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_SUBJECT_RE: Final[re.Pattern[str]] = re.compile(
    r'class="bog"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_SNIPPET_RE: Final[re.Pattern[str]] = re.compile(
    r'class="y2"[^>]*>.*?<span[^>]*>([^<]+)</span>',
    re.IGNORECASE | re.DOTALL,
)
_TIME_RE: Final[re.Pattern[str]] = re.compile(
    r'class="xW"[^>]*>.*?<span[^>]*>([^<]+)</span>',
    re.IGNORECASE | re.DOTALL,
)
_MSG_SUBJECT_RE: Final[re.Pattern[str]] = re.compile(
    r'class="hP"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_MSG_FROM_RE: Final[re.Pattern[str]] = re.compile(
    r'class="gD"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_MSG_BODY_RE: Final[re.Pattern[str]] = re.compile(
    r'class="a3s[^"]*"[^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_ATTACHMENT_RE: Final[re.Pattern[str]] = re.compile(
    r'class="aZo"[^>]*>([^<]+)<',
    re.IGNORECASE,
)

_COMPOSE_SELECTORS: Final[tuple[str, ...]] = (
    "div[gh='cm']",
    "div.T-I.T-I-KE.L3",
    "[aria-label='Compose']",
)
_TO_SELECTORS: Final[tuple[str, ...]] = (
    "textarea[name='to']",
    "input[name='to']",
    "div[aria-label='To']",
)
_SUBJECT_SELECTORS: Final[tuple[str, ...]] = (
    "input[name='subjectbox']",
    "input[name='subject']",
)
_BODY_SELECTORS: Final[tuple[str, ...]] = (
    "div[aria-label='Message Body']",
    "div.Am.Al.editable",
)
_SEND_SELECTORS: Final[tuple[str, ...]] = (
    "div[aria-label*='Send']",
    "div.T-I.atd",
)
_SEARCH_SELECTORS: Final[tuple[str, ...]] = (
    "input[aria-label='Search mail']",
    "input[name='q']",
)

_TYPE_PAUSE_S: Final[float] = 0.2


def _strip_tags(text: str) -> str:
    """Return ``text`` with HTML tags removed (best-effort).

    Args:
        text (str): HTML fragment.

    Returns:
        str: Plain text.

    Examples:
        >>> _strip_tags("<b>Hi</b> there")
        'Hi there'
    """
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_inbox(html: str) -> dict[str, Any]:
    """Parse Gmail inbox rows from saved HTML.

    Args:
        html (str): Saved Gmail inbox HTML.

    Returns:
        dict[str, Any]: ``{messages: [...], count}``.

    Examples:
        >>> html = (
        ...     '<tr class="zA"><td class="yX">Alice</td>'
        ...     '<td><span class="bog">Hello</span></td>'
        ...     '<td class="y2"><span>Preview</span></td>'
        ...     '<td class="xW"><span>10:00</span></td></tr>'
        ... )
        >>> parse_inbox(html)["messages"][0]["from"]
        'Alice'
    """
    messages: list[dict[str, str]] = []
    for row in _INBOX_ROW_RE.finditer(html or ""):
        chunk = row.group(1)
        from_match = _FROM_RE.search(chunk)
        subject_match = _SUBJECT_RE.search(chunk)
        snippet_match = _SNIPPET_RE.search(chunk)
        time_match = _TIME_RE.search(chunk)
        messages.append(
            {
                "from": from_match.group(1).strip() if from_match else "",
                "subject": subject_match.group(1).strip() if subject_match else "",
                "snippet": snippet_match.group(1).strip() if snippet_match else "",
                "time": time_match.group(1).strip() if time_match else "",
            }
        )
    return {"messages": messages, "count": len(messages)}


def parse_message(html: str) -> dict[str, Any]:
    """Parse an open Gmail message from saved HTML.

    Args:
        html (str): Saved Gmail message view HTML.

    Returns:
        dict[str, Any]: ``{subject, from, body, attachments}``.

    Examples:
        >>> html = (
        ...     '<div class="hP">Subject</div><div class="gD">Bob</div>'
        ...     '<div class="a3s">Body text</div><div class="aZo">file.pdf</div>'
        ... )
        >>> parse_message(html)["body"]
        'Body text'
    """
    subject = _MSG_SUBJECT_RE.search(html or "")
    sender = _MSG_FROM_RE.search(html or "")
    body = _MSG_BODY_RE.search(html or "")
    attachments = [m.group(1).strip() for m in _ATTACHMENT_RE.finditer(html or "")]
    return {
        "subject": subject.group(1).strip() if subject else "",
        "from": sender.group(1).strip() if sender else "",
        "body": _strip_tags(body.group(1)) if body else "",
        "attachments": attachments,
    }


class Gmail:
    """Gmail operations over a CDP page + finder."""

    def __init__(
        self,
        page: Page,
        dom: Dom,
        *,
        browser_tools: dict[str, Any] | None = None,
    ) -> None:
        """Bind a page and finder for Gmail.

        Args:
            page (Page): Page bound to the active tab.
            dom (Dom): Finder bound to the same tab.
            browser_tools (dict[str, Any] | None): ``tools.browser`` config section.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(Gmail.__init__)
            True
        """
        self._page = page
        self._dom = dom
        self._browser_tools = browser_tools

    async def run(
        self,
        op: str,
        *,
        query: str = "",
        message_id: str = "",
        to: str = "",
        subject: str = "",
        body: str = "",
    ) -> dict[str, Any]:
        """Dispatch a Gmail recipe operation.

        Args:
            op (str): ``list``, ``read``, ``search``, ``compose``, or ``reply``.
            query (str): Search query for ``search``.
            message_id (str): Subject or sender hint for ``read`` / ``reply``.
            to (str): Recipient for ``compose``.
            subject (str): Subject line for ``compose`` / ``reply``.
            body (str): Message body for ``compose`` / ``reply``.

        Returns:
            dict[str, Any]: Operation result payload.

        Raises:
            RecipeError: When login is required or the op is unknown.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Gmail.run)
            True
        """
        normalized = (op or "").strip().lower()
        if normalized == "list":
            return await self.list_inbox()
        if normalized == "read":
            return await self.read_message(message_id or query)
        if normalized == "search":
            return await self.search_mail(query)
        if normalized == "compose":
            return await self.compose(to, subject, body)
        if normalized == "reply":
            return await self.reply(message_id or query, body)
        msg = f"unknown gmail op: {op!r} (list|read|search|compose|reply)"
        raise RecipeError(msg)

    async def _require_login(self) -> None:
        """Raise when Gmail is not logged in.

        Returns:
            None

        Raises:
            RecipeError: When login or human verification is required.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Gmail._require_login)
            True
        """
        state = await login_state(self._page, "gmail")
        if state.get("logged_in"):
            return
        if state.get("state") == "human_required":
            msg = "Gmail requires human verification (HUMAN_REQUIRED)"
            raise RecipeError(msg)
        msg = "Gmail is not logged in (LOGIN_REQUIRED)"
        raise RecipeError(msg)

    async def list_inbox(self) -> dict[str, Any]:
        """Return inbox rows from the current Gmail view.

        Returns:
            dict[str, Any]: Parsed inbox payload from :func:`parse_inbox`.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Gmail.list_inbox)
            True
        """
        await self._require_login()
        url = validate_egress(_GMAIL_URL, allowlist=GMAIL_EGRESS)
        await self._page.goto(url, wait_until="none")
        html = await self._page.extract_html()
        parsed = parse_inbox(html)
        return {"op": "list", **parsed}

    async def read_message(self, hint: str) -> dict[str, Any]:
        """Open a message matching ``hint`` (subject or sender) and return its body.

        Args:
            hint (str): Subject or sender substring to open.

        Returns:
            dict[str, Any]: Parsed message payload.

        Raises:
            RecipeError: When ``hint`` is empty or no message matches.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Gmail.read_message)
            True
        """
        text = (hint or "").strip()
        if not text:
            msg = "message_id or query is required for gmail read"
            raise RecipeError(msg)
        await self._require_login()
        url = validate_egress(_GMAIL_URL, allowlist=GMAIL_EGRESS)
        await self._page.goto(url, wait_until="none")
        row = await self._dom.find_by_text(text)
        if row is None:
            msg = f"message not found: {text!r}"
            raise RecipeError(msg)
        await row.click()
        await asyncio.sleep(_TYPE_PAUSE_S)
        html = await self._page.extract_html()
        parsed = parse_message(html)
        return {"op": "read", "hint": text, **parsed}

    async def search_mail(self, query: str) -> dict[str, Any]:
        """Search Gmail for ``query`` and return matching inbox rows.

        Args:
            query (str): Gmail search query.

        Returns:
            dict[str, Any]: Parsed inbox rows for the search results view.

        Raises:
            RecipeError: When ``query`` is empty.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Gmail.search_mail)
            True
        """
        text = (query or "").strip()
        if not text:
            msg = "query is required for gmail search"
            raise RecipeError(msg)
        await self._require_login()
        url = validate_egress(
            _GMAIL_SEARCH_URL.format(query=query.replace(" ", "+")),
            allowlist=GMAIL_EGRESS,
        )
        await self._page.goto(url, wait_until="none")
        html = await self._page.extract_html()
        parsed = parse_inbox(html)
        return {"op": "search", "query": text, **parsed}

    async def compose(self, to: str, subject: str, body: str) -> dict[str, Any]:
        """Compose and send a new message (write kill-switch gated).

        Args:
            to (str): Recipient address or name.
            subject (str): Subject line.
            body (str): Message body.

        Returns:
            dict[str, Any]: ``{op: compose, sent: True, to, subject}``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Gmail.compose)
            True
        """
        require_write_allowed("gmail", browser_tools=self._browser_tools)
        await self._require_login()
        await self._page.goto(
            validate_egress(_GMAIL_URL, allowlist=GMAIL_EGRESS), wait_until="none"
        )
        compose_btn = await self._first(_COMPOSE_SELECTORS)
        if compose_btn is None:
            msg = "compose button not found"
            raise RecipeError(msg)
        await compose_btn.click()
        await asyncio.sleep(_TYPE_PAUSE_S)
        await self._fill_fields(to, subject, body)
        send = await self._first(_SEND_SELECTORS)
        if send is None:
            msg = "send button not found"
            raise RecipeError(msg)
        await send.click()
        return {"op": "compose", "sent": True, "to": to, "subject": subject}

    async def reply(self, hint: str, body: str) -> dict[str, Any]:
        """Reply to the message matching ``hint`` (write kill-switch gated).

        Args:
            hint (str): Subject or sender substring identifying the thread.
            body (str): Reply body text.

        Returns:
            dict[str, Any]: ``{op: reply, replied: True, hint}``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Gmail.reply)
            True
        """
        require_write_allowed("gmail", browser_tools=self._browser_tools)
        text = (hint or "").strip()
        if not text:
            msg = "message_id or query is required for gmail reply"
            raise RecipeError(msg)
        await self.read_message(text)
        composer = await self._first(_BODY_SELECTORS)
        if composer is None:
            msg = "reply composer not found"
            raise RecipeError(msg)
        await composer.type(body)
        await asyncio.sleep(_TYPE_PAUSE_S)
        send = await self._first(_SEND_SELECTORS)
        if send is None:
            msg = "send button not found"
            raise RecipeError(msg)
        await send.click()
        return {"op": "reply", "replied": True, "hint": text}

    async def _fill_fields(self, to: str, subject: str, body: str) -> None:
        """Fill compose ``to`` / ``subject`` / ``body`` fields when present.

        Args:
            to (str): Recipient.
            subject (str): Subject line.
            body (str): Message body.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Gmail._fill_fields)
            True
        """
        to_el = await self._first(_TO_SELECTORS)
        if to_el is not None and to:
            await to_el.fill(to)
        subj_el = await self._first(_SUBJECT_SELECTORS)
        if subj_el is not None and subject:
            await subj_el.fill(subject)
        body_el = await self._first(_BODY_SELECTORS)
        if body_el is not None and body:
            await body_el.type(body)

    async def _first(self, selectors: tuple[str, ...]) -> Any:
        """Return the first element matching any selector in ``selectors``.

        Args:
            selectors (tuple[str, ...]): CSS selectors to try in order.

        Returns:
            Any: Element handle or ``None``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(Gmail._first)
            True
        """
        for selector in selectors:
            element = await self._dom.query(selector)
            if element is not None:
                return element
        return None


__all__ = ["GMAIL_EGRESS", "Gmail", "parse_inbox", "parse_message"]
