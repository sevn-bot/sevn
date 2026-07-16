"""X/Twitter timeline HTML scrape helpers for structured post collection.

Module: sevn.browser.recipes.x_timeline
Depends: re

Exports:
    normalize_x_status_url — canonicalize an X status permalink.
    parse_x_timeline_html — scrape ``{tweet_url, author_handle, text}`` from X feed HTML.

Examples:
    >>> from sevn.browser.recipes.x_timeline import normalize_x_status_url
    >>> normalize_x_status_url("/alice/status/1")
    'https://x.com/alice/status/1'
"""

from __future__ import annotations

import re
from typing import Final

__all__ = [
    "normalize_x_status_url",
    "parse_x_timeline_html",
]

_ARTICLE_RE: Final[re.Pattern[str]] = re.compile(
    r"<article\b[^>]*>(.*?)</article>",
    re.IGNORECASE | re.DOTALL,
)
_STATUS_ANCHOR_RE: Final[re.Pattern[str]] = re.compile(
    r'<a\b[^>]*href=["\']([^"\']*?/status/\d+[^"\']*)["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TWEET_TEXT_RE: Final[re.Pattern[str]] = re.compile(
    r'<div[^>]*data-testid=["\']tweetText["\'][^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_STATUS_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:https?://(?:www\.)?(?:x|twitter)\.com)?/([^/\s?#]+)/status/(\d+)",
    re.IGNORECASE,
)
_STATUS_TRAILING_NOISE: Final[frozenset[str]] = frozenset(
    {"analytics", "photo", "likes", "retweets", "quotes", "media", "video"}
)


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


def normalize_x_status_url(href: str) -> str | None:
    """Normalize an X status ``href`` to ``https://x.com/<user>/status/<id>``.

    Strips query strings and trailing path noise (``/analytics``, ``/photo``, …).
    Profile/avatar links without a status id return ``None``.

    Args:
        href (str): Relative or absolute status URL.

    Returns:
        str | None: Canonical permalink, or ``None`` when not a status URL.

    Examples:
        >>> normalize_x_status_url("/alice/status/1111111111111111111?s=20")
        'https://x.com/alice/status/1111111111111111111'
        >>> normalize_x_status_url("/alice/status/1/analytics")
        'https://x.com/alice/status/1'
        >>> normalize_x_status_url("/alice") is None
        True
    """
    match = _STATUS_PATH_RE.search(href or "")
    if not match:
        return None
    user, status_id = match.group(1), match.group(2)
    if not user or user.lower() in {"i", "intent", "share", "search", "hashtag"}:
        return None
    return f"https://x.com/{user}/status/{status_id}"


def _pick_status_href(article_html: str) -> str | None:
    """Return the best ``/status/`` href from one article (timestamp over avatar).

    Prefers an anchor that wraps a ``<time>`` element; otherwise the first status
    link whose path after the id is empty or only query noise.

    Args:
        article_html (str): Inner HTML of one ``<article>``.

    Returns:
        str | None: Raw href, or ``None`` when no status permalink is present.

    Examples:
        >>> href = _pick_status_href(
        ...     '<a href="/a/photo"></a><a href="/a/status/1"><time>1h</time></a>'
        ... )
        >>> href
        '/a/status/1'
    """
    fallback: str | None = None
    for match in _STATUS_ANCHOR_RE.finditer(article_html or ""):
        href = match.group(1) or ""
        inner = match.group(2) or ""
        path_match = _STATUS_PATH_RE.search(href)
        if not path_match:
            continue
        trailing = ""
        remainder = href[path_match.end() :]
        if remainder.startswith("/"):
            trailing = remainder[1:].split("?", 1)[0].split("#", 1)[0].split("/", 1)[0]
        if trailing and trailing.lower() in _STATUS_TRAILING_NOISE:
            if fallback is None:
                fallback = href
            continue
        if "<time" in inner.lower():
            return href
        if fallback is None or not trailing:
            fallback = href
    return fallback


def parse_x_timeline_html(html: str) -> list[dict[str, str]]:
    """Parse X home/timeline HTML into structured posts (DB4).

    Per ``article``: take the timestamp ``/status/`` permalink (not avatar/profile),
    normalize to ``https://x.com/<user>/status/<id>``, read text from
    ``[data-testid="tweetText"]``, and dedupe by ``tweet_url``.

    Args:
        html (str): Saved X feed/page HTML.

    Returns:
        list[dict[str, str]]: ``{tweet_url, author_handle, text}`` rows.

    Examples:
        >>> rows = parse_x_timeline_html(
        ...     '<article><a href="/u/status/9"><time>1h</time></a>'
        ...     '<div data-testid="tweetText">Hi</div></article>'
        ... )
        >>> rows[0]["tweet_url"]
        'https://x.com/u/status/9'
        >>> rows[0]["author_handle"]
        'u'
    """
    posts: list[dict[str, str]] = []
    seen: set[str] = set()
    for article in _ARTICLE_RE.finditer(html or ""):
        body = article.group(1) or ""
        href = _pick_status_href(body)
        if not href:
            continue
        tweet_url = normalize_x_status_url(href)
        if not tweet_url or tweet_url in seen:
            continue
        text_match = _TWEET_TEXT_RE.search(body)
        text = _strip_tags(text_match.group(1) if text_match else "").strip()
        if not text:
            continue
        path = _STATUS_PATH_RE.search(tweet_url)
        if not path:
            continue
        author_handle = path.group(1)
        seen.add(tweet_url)
        posts.append(
            {
                "tweet_url": tweet_url,
                "author_handle": author_handle,
                "text": text,
            }
        )
    return posts
