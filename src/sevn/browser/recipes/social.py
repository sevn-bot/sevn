"""Social-site recipes — read/post/reply/search across major platforms.

A :class:`SocialRecipe` dispatches per-site operations using selector maps and
egress allowlists. Write ops require ``tools.browser.social.<site>.allow_write=true``.

Module: sevn.browser.recipes.social
Depends: asyncio, re, dataclasses, urllib.parse, sevn.browser.auth, sevn.browser.recipes.base

Exports:
    parse_post_html — parse a saved post/page HTML into text metadata.
    parse_comments_html — parse saved comments HTML.
    social_write_allowed — per-site write kill-switch helper.
    SocialRecipe — multi-site social operations over a page/dom pair.

Examples:
    >>> from sevn.browser.recipes.social import parse_post_html
    >>> parse_post_html("<article><p>Hello</p></article>")["text"]
    'Hello'
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import quote_plus

from sevn.browser.auth import login_state
from sevn.browser.recipes.base import RecipeError, validate_egress

X_EGRESS_DOMAINS: Final[tuple[str, ...]] = (
    "x.com",
    "twitter.com",
    "twimg.com",
    "abs.twimg.com",
    "pbs.twimg.com",
    "video.twimg.com",
    "api.twitter.com",
    "api.x.com",
    "t.co",
)

FACEBOOK_EGRESS_DOMAINS: Final[tuple[str, ...]] = (
    "facebook.com",
    "fb.com",
    "fbcdn.net",
    "fbsbx.com",
    "facebook.net",
    "messenger.com",
)

if TYPE_CHECKING:
    from sevn.browser.element import Dom
    from sevn.browser.page import Page

_INSTAGRAM_EGRESS: Final[tuple[str, ...]] = (
    "instagram.com",
    "cdninstagram.com",
    "fbcdn.net",
)
_LINKEDIN_EGRESS: Final[tuple[str, ...]] = ("linkedin.com", "licdn.com")
_REDDIT_EGRESS: Final[tuple[str, ...]] = ("reddit.com", "redd.it", "redditmedia.com")
_TIKTOK_EGRESS: Final[tuple[str, ...]] = ("tiktok.com", "tiktokcdn.com", "tiktokv.com")

_SUPPORTED_SITES: Final[frozenset[str]] = frozenset(
    {"x", "facebook", "instagram", "linkedin", "reddit", "tiktok"}
)

_POST_TEXT_RE: Final[re.Pattern[str]] = re.compile(
    r"<article[^>]*>(.*?)</article>|<div[^>]*data-testid=\"tweetText\"[^>]*>(.*?)</div>",
    re.IGNORECASE | re.DOTALL,
)
_COMMENT_RE: Final[re.Pattern[str]] = re.compile(
    r'class="comment[^"]*"[^>]*>(.*?)</div>|data-testid="comment"[^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_AUTHOR_RE: Final[re.Pattern[str]] = re.compile(
    r'class="author[^"]*"[^>]*>([^<]+)<|data-testid="User-Name"[^>]*>([^<]+)<',
    re.IGNORECASE,
)

_TYPE_PAUSE_S: Final[float] = 0.2


@dataclass(frozen=True)
class _SiteConfig:
    """Per-site home URL, egress allowlist, login key, and selector map."""

    home_url: str
    egress: tuple[str, ...]
    login_site: str
    post_selectors: tuple[str, ...]
    composer_selectors: tuple[str, ...]
    submit_selectors: tuple[str, ...]
    search_url: str


_SITE_CONFIG: Final[dict[str, _SiteConfig]] = {
    "x": _SiteConfig(
        home_url="https://x.com/home",
        egress=X_EGRESS_DOMAINS,
        login_site="x",
        post_selectors=("[data-testid='tweetText']", "article"),
        composer_selectors=("[data-testid='tweetTextarea_0']", "div[role='textbox']"),
        submit_selectors=("[data-testid='tweetButtonInline']", "[data-testid='tweetButton']"),
        search_url="https://x.com/search?q={query}",
    ),
    "facebook": _SiteConfig(
        home_url="https://www.facebook.com/",
        egress=FACEBOOK_EGRESS_DOMAINS,
        login_site="generic",
        post_selectors=("[data-ad-preview='message']", "div[role='article']"),
        composer_selectors=("[aria-label='Create a post']", "div[role='textbox']"),
        submit_selectors=("[aria-label='Post']", "div[role='button']"),
        search_url="https://www.facebook.com/search/top?q={query}",
    ),
    "instagram": _SiteConfig(
        home_url="https://www.instagram.com/",
        egress=_INSTAGRAM_EGRESS,
        login_site="generic",
        post_selectors=("article h1", "article span"),
        composer_selectors=("textarea[aria-label*='comment']", "div[role='textbox']"),
        submit_selectors=("button[type='submit']",),
        search_url="https://www.instagram.com/explore/search/keyword/?q={query}",
    ),
    "linkedin": _SiteConfig(
        home_url="https://www.linkedin.com/feed/",
        egress=_LINKEDIN_EGRESS,
        login_site="generic",
        post_selectors=(".feed-shared-update-v2", "article"),
        composer_selectors=(".ql-editor", "div[role='textbox']"),
        submit_selectors=("button.share-actions__primary-action", "button[type='submit']"),
        search_url="https://www.linkedin.com/search/results/all/?keywords={query}",
    ),
    "reddit": _SiteConfig(
        home_url="https://www.reddit.com/",
        egress=_REDDIT_EGRESS,
        login_site="generic",
        post_selectors=("shreddit-post", "[data-test-id='post-content']"),
        composer_selectors=("div[contenteditable='true']", "textarea"),
        submit_selectors=("button[type='submit']",),
        search_url="https://www.reddit.com/search/?q={query}",
    ),
    "tiktok": _SiteConfig(
        home_url="https://www.tiktok.com/",
        egress=_TIKTOK_EGRESS,
        login_site="generic",
        post_selectors=("[data-e2e='browse-video-desc']", "h1"),
        composer_selectors=("div[contenteditable='true']", "div[role='textbox']"),
        submit_selectors=("button[type='submit']",),
        search_url="https://www.tiktok.com/search?q={query}",
    ),
}


def _strip_tags(text: str) -> str:
    """Return ``text`` with HTML tags removed.

    Args:
        text (str): HTML fragment.

    Returns:
        str: Plain text.

    Examples:
        >>> _strip_tags("<p>Hi</p>")
        'Hi'
    """
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_post_html(html: str) -> dict[str, Any]:
    """Parse post/page text from saved social HTML.

    Args:
        html (str): Saved post or feed HTML.

    Returns:
        dict[str, Any]: ``{text, title}``.

    Examples:
        >>> parse_post_html('<article><p>Hello world</p></article>')["text"]
        'Hello world'
    """
    match = _POST_TEXT_RE.search(html or "")
    if match:
        chunk = match.group(1) or match.group(2) or ""
        text = _strip_tags(chunk)
        if text:
            return {"text": text, "title": text[:120]}
    return {"text": _strip_tags(html or "")[:4000], "title": ""}


def parse_comments_html(html: str, *, limit: int = 20) -> dict[str, Any]:
    """Parse comments/replies from saved social HTML.

    Args:
        html (str): Saved comments section HTML.
        limit (int): Maximum items to return.

    Returns:
        dict[str, Any]: ``{comments: [...], count}``.

    Examples:
        >>> html = '<div class="comment"><span class="author">Ann</span>Nice</div>'
        >>> parse_comments_html(html)["count"] >= 0
        True
    """
    comments: list[dict[str, str]] = []
    for block in _COMMENT_RE.finditer(html or ""):
        if len(comments) >= limit:
            break
        chunk = block.group(1) or block.group(2) or ""
        author = _AUTHOR_RE.search(chunk)
        comments.append(
            {
                "author": _strip_tags(author.group(1) or author.group(2) or "") if author else "",
                "text": _strip_tags(chunk),
            }
        )
    return {"comments": comments, "count": len(comments)}


def social_write_allowed(site: str, *, browser_tools: dict[str, Any] | None = None) -> bool:
    """Return whether write ops are enabled for a social ``site`` (default off).

    Args:
        site (str): Site key (``x``, ``facebook``, …).
        browser_tools (dict[str, Any] | None): ``tools.browser`` config section.

    Returns:
        bool: ``True`` when ``tools.browser.social.<site>.allow_write`` is truthy.

    Examples:
        >>> social_write_allowed("x")
        False
    """
    if not browser_tools:
        return False
    social = browser_tools.get("social")
    if isinstance(social, dict):
        section = social.get(site)
        return bool(isinstance(section, dict) and section.get("allow_write") is True)
    return False


def _require_social_write(site: str, *, browser_tools: dict[str, Any] | None = None) -> None:
    """Raise when social write ops are disabled for ``site``.

    Args:
        site (str): Site key.
        browser_tools (dict[str, Any] | None): ``tools.browser`` config section.

    Returns:
        None

    Raises:
        RecipeError: When the per-site write kill-switch is off.

    Examples:
        >>> _require_social_write("x")  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        RecipeError: social x write ops disabled — set tools.browser.social.x.allow_write=true
    """
    if not social_write_allowed(site, browser_tools=browser_tools):
        msg = f"social {site} write ops disabled — set tools.browser.social.{site}.allow_write=true"
        raise RecipeError(msg)


class SocialRecipe:
    """Multi-site social read/write operations over a CDP page + finder."""

    def __init__(
        self,
        page: Page,
        dom: Dom,
        *,
        browser_tools: dict[str, Any] | None = None,
    ) -> None:
        """Bind a page and finder for social recipes.

        Args:
            page (Page): Page bound to the active tab.
            dom (Dom): Finder bound to the same tab.
            browser_tools (dict[str, Any] | None): ``tools.browser`` config section.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(SocialRecipe.__init__)
            True
        """
        self._page = page
        self._dom = dom
        self._browser_tools = browser_tools

    def _config(self, site: str) -> _SiteConfig:
        """Return the site config for ``site``.

        Args:
            site (str): Site key.

        Returns:
            _SiteConfig: Resolved configuration.

        Raises:
            RecipeError: When ``site`` is unsupported.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(SocialRecipe._config)
            True
        """
        key = (site or "").strip().lower()
        if key not in _SUPPORTED_SITES:
            msg = f"unsupported social site: {site!r} ({', '.join(sorted(_SUPPORTED_SITES))})"
            raise RecipeError(msg)
        return _SITE_CONFIG[key]

    async def run(
        self,
        site: str,
        op: str,
        *,
        target: str = "",
        query: str = "",
        text: str = "",
    ) -> dict[str, Any]:
        """Dispatch a social recipe operation for ``site``.

        Args:
            site (str): ``x``, ``facebook``, ``instagram``, ``linkedin``, ``reddit``, ``tiktok``.
            op (str): ``read``, ``post``, ``reply``, ``read_replies``, or ``search``.
            target (str): URL or post id for read/reply/read_replies.
            query (str): Search query for ``search``.
            text (str): Body for ``post`` / ``reply``.

        Returns:
            dict[str, Any]: Operation result payload.

        Raises:
            RecipeError: When params are invalid.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SocialRecipe.run)
            True
        """
        cfg = self._config(site)
        site_key = site.strip().lower()
        normalized = (op or "").strip().lower()
        if normalized == "read":
            return await self.read(site_key, cfg, target)
        if normalized == "search":
            return await self.search(site_key, cfg, query or target)
        if normalized == "read_replies":
            return await self.read_replies(site_key, cfg, target)
        if normalized == "post":
            return await self.post(site_key, cfg, text)
        if normalized == "reply":
            return await self.reply(site_key, cfg, target, text)
        msg = f"unknown social op: {op!r} (read|post|reply|read_replies|search)"
        raise RecipeError(msg)

    async def _require_login(self, cfg: _SiteConfig) -> None:
        """Raise when the site session is not logged in.

        Args:
            cfg (_SiteConfig): Site configuration.

        Returns:
            None

        Raises:
            RecipeError: When login or human verification is required.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SocialRecipe._require_login)
            True
        """
        state = await login_state(self._page, cfg.login_site)
        if state.get("logged_in"):
            return
        if state.get("state") == "human_required":
            msg = f"{cfg.login_site} requires human verification (HUMAN_REQUIRED)"
            raise RecipeError(msg)
        msg = f"{cfg.login_site} is not logged in (LOGIN_REQUIRED)"
        raise RecipeError(msg)

    async def read(self, site_key: str, cfg: _SiteConfig, target: str) -> dict[str, Any]:
        """Read a post or feed page.

        Args:
            site_key (str): Site key (``x``, ``facebook``, …).
            cfg (_SiteConfig): Site configuration.
            target (str): URL to open; home feed when empty.

        Returns:
            dict[str, Any]: Parsed post text payload.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SocialRecipe.read)
            True
        """
        url = target.strip() if target else cfg.home_url
        if url.startswith("http"):
            validate_egress(url, allowlist=cfg.egress)
        else:
            url = cfg.home_url
        await self._page.goto(url, wait_until="none")
        html = await self._page.extract_html()
        parsed = parse_post_html(html)
        return {"site": site_key, "op": "read", "url": url, **parsed}

    async def search(self, site_key: str, cfg: _SiteConfig, query: str) -> dict[str, Any]:
        """Search the site for ``query``.

        Args:
            site_key (str): Site key.
            cfg (_SiteConfig): Site configuration.
            query (str): Search text.

        Returns:
            dict[str, Any]: ``{searched: query, url}``.

        Raises:
            RecipeError: When ``query`` is empty.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SocialRecipe.search)
            True
        """
        text = (query or "").strip()
        if not text:
            msg = "query is required for social search"
            raise RecipeError(msg)
        url = validate_egress(
            cfg.search_url.format(query=quote_plus(text)),
            allowlist=cfg.egress,
        )
        await self._page.goto(url, wait_until="none")
        return {"site": site_key, "op": "search", "searched": text, "url": url}

    async def read_replies(self, site_key: str, cfg: _SiteConfig, target: str) -> dict[str, Any]:
        """Return replies/comments for a post at ``target``.

        Args:
            site_key (str): Site key.
            cfg (_SiteConfig): Site configuration.
            target (str): Post URL.

        Returns:
            dict[str, Any]: Parsed comments list.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SocialRecipe.read_replies)
            True
        """
        url = target.strip() if target else cfg.home_url
        if url.startswith("http"):
            validate_egress(url, allowlist=cfg.egress)
        else:
            url = cfg.home_url
        await self._page.goto(url, wait_until="none")
        html = await self._page.extract_html()
        parsed = parse_comments_html(html)
        return {"site": site_key, "op": "read_replies", "url": url, **parsed}

    async def post(self, site_key: str, cfg: _SiteConfig, text: str) -> dict[str, Any]:
        """Compose and publish a new post (write kill-switch gated).

        Args:
            site_key (str): Site key.
            cfg (_SiteConfig): Site configuration.
            text (str): Post body.

        Returns:
            dict[str, Any]: ``{posted: True, site, text}``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SocialRecipe.post)
            True
        """
        _require_social_write(site_key, browser_tools=self._browser_tools)
        body = (text or "").strip()
        if not body:
            msg = "text is required for social post"
            raise RecipeError(msg)
        await self._require_login(cfg)
        await self._page.goto(cfg.home_url, wait_until="none")
        composer = await self._first(cfg.composer_selectors)
        if composer is None:
            msg = "composer not found"
            raise RecipeError(msg)
        await composer.type(body)
        await asyncio.sleep(_TYPE_PAUSE_S)
        submit = await self._first(cfg.submit_selectors)
        if submit is None:
            msg = "submit button not found"
            raise RecipeError(msg)
        await submit.click()
        return {"site": site_key, "op": "post", "posted": True, "text": body}

    async def reply(
        self, site_key: str, cfg: _SiteConfig, target: str, text: str
    ) -> dict[str, Any]:
        """Reply on a post at ``target`` (write kill-switch gated).

        Args:
            site_key (str): Site key.
            cfg (_SiteConfig): Site configuration.
            target (str): Post URL or text hint.
            text (str): Reply body.

        Returns:
            dict[str, Any]: ``{replied: True, site, target}``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SocialRecipe.reply)
            True
        """
        _require_social_write(site_key, browser_tools=self._browser_tools)
        body = (text or "").strip()
        if not body:
            msg = "text is required for social reply"
            raise RecipeError(msg)
        await self._require_login(cfg)
        if target.strip().startswith("http"):
            validate_egress(target.strip(), allowlist=cfg.egress)
            await self._page.goto(target.strip(), wait_until="none")
        else:
            await self._page.goto(cfg.home_url, wait_until="none")
        composer = await self._first(cfg.composer_selectors)
        if composer is None:
            msg = "reply composer not found"
            raise RecipeError(msg)
        await composer.type(body)
        await asyncio.sleep(_TYPE_PAUSE_S)
        submit = await self._first(cfg.submit_selectors)
        if submit is None:
            msg = "reply submit button not found"
            raise RecipeError(msg)
        await submit.click()
        return {"site": site_key, "op": "reply", "replied": True, "target": target}

    async def _first(self, selectors: tuple[str, ...]) -> Any:
        """Return the first element matching any selector in ``selectors``.

        Args:
            selectors (tuple[str, ...]): CSS selectors to try in order.

        Returns:
            Any: Element handle or ``None``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SocialRecipe._first)
            True
        """
        for selector in selectors:
            element = await self._dom.query(selector)
            if element is not None:
                return element
        return None


__all__ = ["SocialRecipe", "parse_comments_html", "parse_post_html", "social_write_allowed"]
