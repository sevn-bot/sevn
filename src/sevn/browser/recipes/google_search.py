"""Google Search recipe — organic results and AI Overview / Gemini ask mode (D11).

Scrapes Google Search result pages for organic hits and People-Also-Ask blocks.
``mode=ask`` prefers the on-page AI Overview panel and falls back to
``gemini.google.com`` when no overview is present.

Module: sevn.browser.recipes.google_search
Depends: re, urllib.parse, sevn.browser.page, sevn.browser.recipes.base

Exports:
    parse_search_results — parse organic results + PAA from saved HTML.
    parse_ai_overview — parse AI Overview answer + citations from saved HTML.
    parse_gemini_answer — parse a Gemini response page from saved HTML.
    GoogleSearch — live recipe over a page/dom pair.

Examples:
    >>> from sevn.browser.recipes.google_search import parse_search_results
    >>> parse_search_results("<html></html>")["count"]
    0
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import quote_plus

from sevn.browser.recipes.base import RecipeError, validate_egress

if TYPE_CHECKING:
    from sevn.browser.element import Dom
    from sevn.browser.page import Page

GOOGLE_SEARCH_EGRESS: Final[tuple[str, ...]] = ("google.com", "gemini.google.com")
_GOOGLE_SEARCH_URL: Final[str] = "https://www.google.com/search?q={query}&hl=en"
_GEMINI_URL: Final[str] = "https://gemini.google.com/app?q={query}"

_LINK_TITLE_RE: Final[re.Pattern[str]] = re.compile(
    r'<h3[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>',
    re.IGNORECASE,
)
_SNIPPET_RE: Final[re.Pattern[str]] = re.compile(
    r'class="VwiC3b"[^>]*>.*?<span[^>]*>([^<]+)</span>',
    re.IGNORECASE | re.DOTALL,
)
_PAA_RE: Final[re.Pattern[str]] = re.compile(
    r'class="match-mod-horizontal-padding"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_AI_ANSWER_RE: Final[re.Pattern[str]] = re.compile(
    r'class="(?:Z26q7c|ai-overview|WaaZC)"[^>]*>.*?<span[^>]*>([^<]+)</span>',
    re.IGNORECASE | re.DOTALL,
)
_AI_CITATION_RE: Final[re.Pattern[str]] = re.compile(
    r'<a[^>]+href="(https?://[^"]+)"[^>]*>([^<]+)</a>',
    re.IGNORECASE,
)
_GEMINI_ANSWER_RE: Final[re.Pattern[str]] = re.compile(
    r'class="model-response-text"[^>]*>([^<]+)<',
    re.IGNORECASE,
)


def parse_search_results(html: str) -> dict[str, Any]:
    """Parse organic Google results and People-Also-Ask from saved HTML.

    Args:
        html (str): Saved Google Search results page HTML.

    Returns:
        dict[str, Any]: ``{results: [...], people_also_ask: [...], count}``.

    Examples:
        >>> html = (
        ...     '<div class="g"><h3><a href="https://a.example">Title A</a></h3>'
        ...     '<div class="VwiC3b"><span>Snippet A</span></div></div>'
        ... )
        >>> out = parse_search_results(html)
        >>> out["results"][0]["title"]
        'Title A'
    """
    results: list[dict[str, str]] = []
    for match in _LINK_TITLE_RE.finditer(html or ""):
        url, title = match.group(1), match.group(2).strip()
        if url.startswith("/"):
            continue
        snippet = ""
        tail = html[match.end() : match.end() + 800]
        snippet_match = _SNIPPET_RE.search(tail)
        if snippet_match:
            snippet = snippet_match.group(1).strip()
        results.append({"title": title, "url": url, "snippet": snippet})
    paa = [m.group(1).strip() for m in _PAA_RE.finditer(html or "")]
    return {"results": results, "people_also_ask": paa, "count": len(results)}


def parse_ai_overview(html: str) -> dict[str, Any] | None:
    """Parse an AI Overview answer and citations from saved Google HTML.

    Args:
        html (str): Saved Google Search page HTML containing an AI Overview block.

    Returns:
        dict[str, Any] | None: ``{answer, citations, source: ai_overview}`` or ``None``.

    Examples:
        >>> html = (
        ...     '<div class="ai-overview-panel"><div class="Z26q7c">'
        ...     '<span>Python is a language.</span></div>'
        ...     '<a href="https://python.org">python.org</a></div>'
        ... )
        >>> parse_ai_overview(html)["answer"]
        'Python is a language.'
    """
    answer_match = _AI_ANSWER_RE.search(html or "")
    if not answer_match:
        return None
    answer = answer_match.group(1).strip()
    citations: list[dict[str, str]] = []
    for url, label in _AI_CITATION_RE.findall(html or ""):
        if "google." in url and "/url?" in url:
            continue
        citations.append({"url": url, "label": label.strip()})
    return {"answer": answer, "citations": citations, "source": "ai_overview"}


def parse_gemini_answer(html: str) -> dict[str, Any]:
    """Parse a Gemini response page from saved HTML.

    Args:
        html (str): Saved ``gemini.google.com`` response HTML.

    Returns:
        dict[str, Any]: ``{answer, citations, source: gemini}``.

    Examples:
        >>> html = (
        ...     '<div class="model-response-text">Gemini answer here.</div>'
        ...     '<a href="https://docs.example">docs</a>'
        ... )
        >>> parse_gemini_answer(html)["answer"]
        'Gemini answer here.'
    """
    answer_match = _GEMINI_ANSWER_RE.search(html or "")
    answer = answer_match.group(1).strip() if answer_match else ""
    citations = [
        {"url": url, "label": label.strip()} for url, label in _AI_CITATION_RE.findall(html or "")
    ]
    return {"answer": answer, "citations": citations, "source": "gemini"}


class GoogleSearch:
    """Google Search operations over a CDP page + finder."""

    def __init__(self, page: Page, dom: Dom) -> None:
        """Bind a page and finder for Google Search.

        Args:
            page (Page): Page bound to the active tab.
            dom (Dom): Finder bound to the same tab.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(GoogleSearch.__init__)
            True
        """
        self._page = page
        self._dom = dom

    async def search(self, query: str, *, mode: str = "results") -> dict[str, Any]:
        """Run a Google Search in ``results`` or ``ask`` mode (D11).

        Args:
            query (str): Search query text.
            mode (str): ``results`` (organic + PAA) or ``ask`` (AI Overview / Gemini).

        Returns:
            dict[str, Any]: Parsed results or synthesized answer payload.

        Raises:
            RecipeError: When ``query`` is empty or ``mode`` is unknown.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(GoogleSearch.search)
            True
        """
        text = (query or "").strip()
        if not text:
            msg = "query is required for google_search"
            raise RecipeError(msg)
        normalized_mode = (mode or "results").strip().lower()
        if normalized_mode == "results":
            return await self._search_results(text)
        if normalized_mode == "ask":
            return await self._search_ask(text)
        msg = f"unknown google_search mode: {mode!r} (results|ask)"
        raise RecipeError(msg)

    async def _search_results(self, query: str) -> dict[str, Any]:
        """Navigate to Google and return parsed organic results + PAA.

        Args:
            query (str): Search query text.

        Returns:
            dict[str, Any]: Parsed results payload.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(GoogleSearch._search_results)
            True
        """
        url = validate_egress(
            _GOOGLE_SEARCH_URL.format(query=quote_plus(query)),
            allowlist=GOOGLE_SEARCH_EGRESS,
        )
        await self._page.goto(url, wait_until="none")
        html = await self._page.extract_html()
        parsed = parse_search_results(html)
        return {"query": query, "mode": "results", **parsed}

    async def _search_ask(self, query: str) -> dict[str, Any]:
        """Return AI Overview text or fall back to Gemini (D11).

        Args:
            query (str): Search query text.

        Returns:
            dict[str, Any]: Answer payload with citations.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(GoogleSearch._search_ask)
            True
        """
        url = validate_egress(
            _GOOGLE_SEARCH_URL.format(query=quote_plus(query)),
            allowlist=GOOGLE_SEARCH_EGRESS,
        )
        await self._page.goto(url, wait_until="none")
        html = await self._page.extract_html()
        overview = parse_ai_overview(html)
        if overview:
            return {"query": query, "mode": "ask", **overview}
        gemini_url = validate_egress(
            _GEMINI_URL.format(query=quote_plus(query)),
            allowlist=GOOGLE_SEARCH_EGRESS,
        )
        await self._page.goto(gemini_url, wait_until="none")
        gemini_html = await self._page.extract_html()
        gemini = parse_gemini_answer(gemini_html)
        return {"query": query, "mode": "ask", **gemini}


__all__ = [
    "GOOGLE_SEARCH_EGRESS",
    "GoogleSearch",
    "parse_ai_overview",
    "parse_gemini_answer",
    "parse_search_results",
]
