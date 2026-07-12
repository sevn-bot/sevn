"""startup.jobs extractor (own-CDP browser).

Navigates the public search page with the sevn CDP engine and parses listing anchors.
"""

from __future__ import annotations

import httpx

from ..models import SearchQuery
from .base import ExtractorResult
from .browser_board import BrowserBoard, run_board

ID = "startupjobs"
_ORIGIN = "https://startup.jobs"
_DEFAULT_TERM = "software engineer"


def _build_urls(query: SearchQuery) -> list[str]:
    urls: list[str] = []
    for term in query.search_terms or [_DEFAULT_TERM]:
        urls.append(str(httpx.URL(_ORIGIN, params={"q": term})))
    return urls


def run(query: SearchQuery) -> ExtractorResult:
    """Navigate startup.jobs search results and parse job listings via own-CDP."""
    board = BrowserBoard(id=ID, origin=_ORIGIN, href_pattern=r"/\d+-", build_urls=_build_urls)
    return run_board(board, query)
