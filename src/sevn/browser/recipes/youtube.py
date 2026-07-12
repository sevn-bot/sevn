"""YouTube recipe — search, video info, comments, and gated comment/reply writes.

Read ops scrape watch and search pages. Write ops (``comment``, ``reply``) require
login (W6) and ``tools.browser.youtube.allow_write=true`` (D8).

Module: sevn.browser.recipes.youtube
Depends: asyncio, re, urllib.parse, sevn.browser.auth, sevn.browser.recipes.base

Exports:
    parse_search_results — parse video rows from saved search HTML.
    parse_video_info — parse watch-page metadata from saved HTML.
    parse_comments — parse top comments from saved HTML.
    parse_replies — parse expanded reply threads from saved HTML.
    YouTube — live recipe over a page/dom pair.

Examples:
    >>> from sevn.browser.recipes.youtube import parse_search_results
    >>> parse_search_results("<html></html>")["count"]
    0
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import quote_plus, urlparse

from sevn.browser.auth import login_state
from sevn.browser.recipes.base import RecipeError, require_write_allowed, validate_egress

if TYPE_CHECKING:
    from sevn.browser.element import Dom
    from sevn.browser.page import Page

YOUTUBE_EGRESS: Final[tuple[str, ...]] = (
    "youtube.com",
    "youtu.be",
    "googlevideo.com",
    "ytimg.com",
    "google.com",
)
_SEARCH_URL: Final[str] = "https://www.youtube.com/results?search_query={query}"

_VIDEO_RE: Final[re.Pattern[str]] = re.compile(
    r'<a[^>]+href="(/watch\?v=[^"]+)"[^>]*><span[^>]*>([^<]+)</span>',
    re.IGNORECASE,
)
_CHANNEL_RE: Final[re.Pattern[str]] = re.compile(
    r'class="[^"]*channel-name[^"]*"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_VIEWS_RE: Final[re.Pattern[str]] = re.compile(
    r'class="[^"]*inline-metadata-item[^"]*"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_TITLE_RE: Final[re.Pattern[str]] = re.compile(
    r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"',
    re.IGNORECASE,
)
_DESC_RE: Final[re.Pattern[str]] = re.compile(
    r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
    re.IGNORECASE,
)
_LIKES_RE: Final[re.Pattern[str]] = re.compile(
    r'aria-label="([0-9,]+)\s+likes?"',
    re.IGNORECASE,
)
_COMMENT_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r'id="comment[^"]*"[^>]*>(.*?)</ytd-comment-renderer>',
    re.IGNORECASE | re.DOTALL,
)
_COMMENT_AUTHOR_RE: Final[re.Pattern[str]] = re.compile(
    r'id="author-text"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_COMMENT_TEXT_RE: Final[re.Pattern[str]] = re.compile(
    r'id="content-text"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_COMMENT_LIKES_RE: Final[re.Pattern[str]] = re.compile(
    r'id="vote-count-middle"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_REPLY_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r'class="ytd-comment-replies-renderer"[^>]*>(.*?)</ytd-comment-replies-renderer>',
    re.IGNORECASE | re.DOTALL,
)

_COMMENT_BOX_SELECTORS: Final[tuple[str, ...]] = (
    "#placeholder-area",
    "#simplebox-placeholder",
    "div#placeholder-area",
)
_REPLY_BOX_SELECTORS: Final[tuple[str, ...]] = (
    "#contenteditable-root",
    "div#contenteditable-root",
)
_SUBMIT_SELECTORS: Final[tuple[str, ...]] = (
    "#submit-button",
    "ytd-button-renderer#submit-button",
)

_TYPE_PAUSE_S: Final[float] = 0.2


def _normalize_watch_url(url: str) -> str:
    """Return a canonical YouTube watch URL for ``url`` or a bare video id.

    Args:
        url (str): Full URL or ``/watch?v=…`` path or 11-char id.

    Returns:
        str: Absolute https watch URL.

    Raises:
        RecipeError: When the value cannot be parsed as a YouTube video ref.

    Examples:
        >>> _normalize_watch_url("dQw4w9WgXcQ").endswith("v=dQw4w9WgXcQ")
        True
    """
    text = (url or "").strip()
    if not text:
        msg = "url is required for youtube info/comments"
        raise RecipeError(msg)
    if text.startswith("http"):
        parsed = urlparse(text)
        if "youtube.com" in (parsed.hostname or "") or "youtu.be" in (parsed.hostname or ""):
            return validate_egress(text, allowlist=YOUTUBE_EGRESS)
        msg = f"not a youtube url: {text!r}"
        raise RecipeError(msg)
    if text.startswith("/watch"):
        return validate_egress(f"https://www.youtube.com{text}", allowlist=YOUTUBE_EGRESS)
    if re.fullmatch(r"[\w-]{11}", text):
        return validate_egress(
            f"https://www.youtube.com/watch?v={text}",
            allowlist=YOUTUBE_EGRESS,
        )
    msg = f"invalid youtube video ref: {text!r}"
    raise RecipeError(msg)


def parse_search_results(html: str) -> dict[str, Any]:
    """Parse YouTube search results from saved HTML.

    Args:
        html (str): Saved search results page HTML.

    Returns:
        dict[str, Any]: ``{videos: [...], count}``.

    Examples:
        >>> html = (
        ...     '<a href="/watch?v=abc12345678"><span>My Video</span></a>'
        ...     '<span class="inline-metadata-item">1.2M views</span>'
        ... )
        >>> parse_search_results(html)["videos"][0]["title"]
        'My Video'
    """
    videos: list[dict[str, str]] = []
    for match in _VIDEO_RE.finditer(html or ""):
        path, title = match.group(1), match.group(2).strip()
        tail = html[match.end() : match.end() + 400]
        channel = _CHANNEL_RE.search(tail)
        views = _VIEWS_RE.search(tail)
        videos.append(
            {
                "title": title,
                "url": f"https://www.youtube.com{path}",
                "channel": channel.group(1).strip() if channel else "",
                "views": views.group(1).strip() if views else "",
            }
        )
    return {"videos": videos, "count": len(videos)}


def parse_video_info(html: str) -> dict[str, Any]:
    """Parse watch-page metadata from saved HTML.

    Args:
        html (str): Saved watch page HTML.

    Returns:
        dict[str, Any]: ``{title, description, views, likes, channel}``.

    Examples:
        >>> html = (
        ...     '<meta property="og:title" content="Demo">'
        ...     '<meta property="og:description" content="A demo video">'
        ...     '<div aria-label="100 likes"></div>'
        ... )
        >>> parse_video_info(html)["title"]
        'Demo'
    """
    title = _TITLE_RE.search(html or "")
    desc = _DESC_RE.search(html or "")
    likes = _LIKES_RE.search(html or "")
    channel = _CHANNEL_RE.search(html or "")
    views = _VIEWS_RE.search(html or "")
    return {
        "title": title.group(1).strip() if title else "",
        "description": desc.group(1).strip() if desc else "",
        "likes": likes.group(1).strip() if likes else "",
        "channel": channel.group(1).strip() if channel else "",
        "views": views.group(1).strip() if views else "",
    }


def parse_comments(html: str, *, limit: int = 20) -> dict[str, Any]:
    """Parse top comments from saved watch-page HTML.

    Args:
        html (str): Saved comments section HTML.
        limit (int): Maximum comments to return.

    Returns:
        dict[str, Any]: ``{comments: [...], count}``.

    Examples:
        >>> html = (
        ...     '<div id="comment-content"><span id="author-text">Ann</span>'
        ...     '<span id="content-text">Great video</span>'
        ...     '<span id="vote-count-middle">5</span></div>'
        ... )
        >>> parse_comments(html)["comments"][0]["author"]
        'Ann'
    """
    comments: list[dict[str, str]] = []
    for block in _COMMENT_BLOCK_RE.finditer(html or ""):
        if len(comments) >= limit:
            break
        chunk = block.group(1)
        author = _COMMENT_AUTHOR_RE.search(chunk)
        text = _COMMENT_TEXT_RE.search(chunk)
        likes = _COMMENT_LIKES_RE.search(chunk)
        if author or text:
            comments.append(
                {
                    "author": author.group(1).strip() if author else "",
                    "text": text.group(1).strip() if text else "",
                    "likes": likes.group(1).strip() if likes else "",
                }
            )
    if not comments:
        for author in _COMMENT_AUTHOR_RE.finditer(html or ""):
            if len(comments) >= limit:
                break
            text = _COMMENT_TEXT_RE.search(html or "")
            comments.append(
                {
                    "author": author.group(1).strip(),
                    "text": text.group(1).strip() if text else "",
                    "likes": "",
                }
            )
            break
    return {"comments": comments, "count": len(comments)}


def parse_replies(html: str, *, limit: int = 20) -> dict[str, Any]:
    """Parse expanded reply threads from saved HTML.

    Args:
        html (str): Saved replies section HTML.
        limit (int): Maximum replies to return.

    Returns:
        dict[str, Any]: ``{replies: [...], count}``.

    Examples:
        >>> html = (
        ...     '<ytd-comment-replies-renderer class="ytd-comment-replies-renderer">'
        ...     '<span id="author-text">Bob</span>'
        ...     '<span id="content-text">Thanks!</span>'
        ...     '</ytd-comment-replies-renderer>'
        ... )
        >>> parse_replies(html)["replies"][0]["author"]
        'Bob'
    """
    replies: list[dict[str, str]] = []
    for block in _REPLY_BLOCK_RE.finditer(html or ""):
        if len(replies) >= limit:
            break
        chunk = block.group(1)
        author = _COMMENT_AUTHOR_RE.search(chunk)
        text = _COMMENT_TEXT_RE.search(chunk)
        if author or text:
            replies.append(
                {
                    "author": author.group(1).strip() if author else "",
                    "text": text.group(1).strip() if text else "",
                }
            )
    return {"replies": replies, "count": len(replies)}


class YouTube:
    """YouTube operations over a CDP page + finder."""

    def __init__(
        self,
        page: Page,
        dom: Dom,
        *,
        browser_tools: dict[str, Any] | None = None,
    ) -> None:
        """Bind a page and finder for YouTube.

        Args:
            page (Page): Page bound to the active tab.
            dom (Dom): Finder bound to the same tab.
            browser_tools (dict[str, Any] | None): ``tools.browser`` config section.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(YouTube.__init__)
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
        url: str = "",
        text: str = "",
        comment_hint: str = "",
    ) -> dict[str, Any]:
        """Dispatch a YouTube recipe operation.

        Args:
            op (str): ``search``, ``info``, ``comments``, ``read_replies``, ``comment``, ``reply``.
            query (str): Search query for ``search``.
            url (str): Video URL for read/write ops.
            text (str): Comment/reply body for write ops.
            comment_hint (str): Author/text hint to locate a comment for ``reply`` / ``read_replies``.

        Returns:
            dict[str, Any]: Operation result payload.

        Raises:
            RecipeError: When params are missing or the op is unknown.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(YouTube.run)
            True
        """
        normalized = (op or "").strip().lower()
        if normalized == "search":
            return await self.search(query)
        if normalized == "info":
            return await self.info(url or query)
        if normalized == "comments":
            return await self.comments(url or query)
        if normalized == "read_replies":
            return await self.read_replies(url or query, comment_hint)
        if normalized == "comment":
            return await self.comment(url or query, text)
        if normalized == "reply":
            return await self.reply(url or query, comment_hint, text)
        msg = f"unknown youtube op: {op!r} (search|info|comments|read_replies|comment|reply)"
        raise RecipeError(msg)

    async def search(self, query: str) -> dict[str, Any]:
        """Search YouTube for ``query`` and return matching videos.

        Args:
            query (str): Free-text search query.

        Returns:
            dict[str, Any]: Parsed search results.

        Raises:
            RecipeError: When ``query`` is empty.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(YouTube.search)
            True
        """
        text = (query or "").strip()
        if not text:
            msg = "query is required for youtube search"
            raise RecipeError(msg)
        target = validate_egress(
            _SEARCH_URL.format(query=quote_plus(text)),
            allowlist=YOUTUBE_EGRESS,
        )
        await self._page.goto(target, wait_until="none")
        html = await self._page.extract_html()
        parsed = parse_search_results(html)
        return {"op": "search", "query": text, **parsed}

    async def info(self, url: str) -> dict[str, Any]:
        """Open a watch page and return video metadata.

        Args:
            url (str): Watch URL or video id.

        Returns:
            dict[str, Any]: Parsed video info payload.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(YouTube.info)
            True
        """
        target = _normalize_watch_url(url)
        await self._page.goto(target, wait_until="none")
        html = await self._page.extract_html()
        parsed = parse_video_info(html)
        return {"op": "info", "url": target, **parsed}

    async def comments(self, url: str) -> dict[str, Any]:
        """Return top comments for a watch page.

        Args:
            url (str): Watch URL or video id.

        Returns:
            dict[str, Any]: Parsed comments list.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(YouTube.comments)
            True
        """
        target = _normalize_watch_url(url)
        await self._page.goto(target, wait_until="none")
        html = await self._page.extract_html(selector="ytd-comments#comments")
        if not html:
            html = await self._page.extract_html()
        parsed = parse_comments(html)
        return {"op": "comments", "url": target, **parsed}

    async def read_replies(self, url: str, comment_hint: str) -> dict[str, Any]:
        """Expand replies for the comment matching ``comment_hint``.

        Args:
            url (str): Watch URL or video id.
            comment_hint (str): Author or text substring identifying the comment.

        Returns:
            dict[str, Any]: Parsed replies list.

        Raises:
            RecipeError: When ``comment_hint`` is empty or no comment matches.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(YouTube.read_replies)
            True
        """
        hint = (comment_hint or "").strip()
        if not hint:
            msg = "comment_hint is required for youtube read_replies"
            raise RecipeError(msg)
        target = _normalize_watch_url(url)
        await self._page.goto(target, wait_until="none")
        comment = await self._dom.find_by_text(hint)
        if comment is None:
            msg = f"comment not found: {hint!r}"
            raise RecipeError(msg)
        await comment.click()
        await asyncio.sleep(_TYPE_PAUSE_S)
        html = await self._page.extract_html()
        parsed = parse_replies(html)
        return {"op": "read_replies", "url": target, "comment_hint": hint, **parsed}

    async def _require_login(self) -> None:
        """Raise when YouTube is not logged in.

        Returns:
            None

        Raises:
            RecipeError: When login or human verification is required.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(YouTube._require_login)
            True
        """
        state = await login_state(self._page, "youtube")
        if state.get("logged_in"):
            return
        if state.get("state") == "human_required":
            msg = "YouTube requires human verification (HUMAN_REQUIRED)"
            raise RecipeError(msg)
        msg = "YouTube is not logged in (LOGIN_REQUIRED)"
        raise RecipeError(msg)

    async def comment(self, url: str, text: str) -> dict[str, Any]:
        """Post a top-level comment (write kill-switch gated).

        Args:
            url (str): Watch URL or video id.
            text (str): Comment body.

        Returns:
            dict[str, Any]: ``{op: comment, posted: True, url}``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(YouTube.comment)
            True
        """
        require_write_allowed("youtube", browser_tools=self._browser_tools)
        body = (text or "").strip()
        if not body:
            msg = "text is required for youtube comment"
            raise RecipeError(msg)
        await self._require_login()
        target = _normalize_watch_url(url)
        await self._page.goto(target, wait_until="none")
        box = await self._first(_COMMENT_BOX_SELECTORS)
        if box is None:
            msg = "comment box not found"
            raise RecipeError(msg)
        await box.type(body)
        await asyncio.sleep(_TYPE_PAUSE_S)
        submit = await self._first(_SUBMIT_SELECTORS)
        if submit is None:
            msg = "comment submit button not found"
            raise RecipeError(msg)
        await submit.click()
        return {"op": "comment", "posted": True, "url": target}

    async def reply(self, url: str, comment_hint: str, text: str) -> dict[str, Any]:
        """Reply to a comment matching ``comment_hint`` (write kill-switch gated).

        Args:
            url (str): Watch URL or video id.
            comment_hint (str): Author or text substring identifying the comment.
            text (str): Reply body.

        Returns:
            dict[str, Any]: ``{op: reply, replied: True, url, comment_hint}``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(YouTube.reply)
            True
        """
        require_write_allowed("youtube", browser_tools=self._browser_tools)
        body = (text or "").strip()
        hint = (comment_hint or "").strip()
        if not body or not hint:
            msg = "comment_hint and text are required for youtube reply"
            raise RecipeError(msg)
        await self._require_login()
        target = _normalize_watch_url(url)
        await self._page.goto(target, wait_until="none")
        comment = await self._dom.find_by_text(hint)
        if comment is None:
            msg = f"comment not found: {hint!r}"
            raise RecipeError(msg)
        await comment.click()
        await asyncio.sleep(_TYPE_PAUSE_S)
        box = await self._first(_REPLY_BOX_SELECTORS)
        if box is None:
            msg = "reply box not found"
            raise RecipeError(msg)
        await box.type(body)
        await asyncio.sleep(_TYPE_PAUSE_S)
        submit = await self._first(_SUBMIT_SELECTORS)
        if submit is None:
            msg = "reply submit button not found"
            raise RecipeError(msg)
        await submit.click()
        return {"op": "reply", "replied": True, "url": target, "comment_hint": hint}

    async def _first(self, selectors: tuple[str, ...]) -> Any:
        """Return the first element matching any selector in ``selectors``.

        Args:
            selectors (tuple[str, ...]): CSS selectors to try in order.

        Returns:
            Any: Element handle or ``None``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(YouTube._first)
            True
        """
        for selector in selectors:
            element = await self._dom.query(selector)
            if element is not None:
                return element
        return None


__all__ = [
    "YOUTUBE_EGRESS",
    "YouTube",
    "parse_comments",
    "parse_replies",
    "parse_search_results",
    "parse_video_info",
]
