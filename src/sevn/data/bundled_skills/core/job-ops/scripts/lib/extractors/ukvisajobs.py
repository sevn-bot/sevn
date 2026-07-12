"""UK Visa Jobs extractor (own-CDP browser).

The board is Cloudflare-gated; this navigates the public search page
with the sevn CDP engine and parses listing anchors. UK visa-sponsorship board.
"""

from __future__ import annotations

import httpx

from ..models import SearchQuery
from .base import ExtractorResult
from .browser_board import BrowserBoard, run_board

ID = "ukvisajobs"
_ORIGIN = "https://www.ukvisajobs.com"
_DEFAULT_TERM = "software engineer"


def _build_urls(query: SearchQuery) -> list[str]:
    urls: list[str] = []
    for term in query.search_terms or [_DEFAULT_TERM]:
        urls.append(str(httpx.URL(f"{_ORIGIN}/jobs", params={"search": term})))
    return urls


def run(query: SearchQuery) -> ExtractorResult:
    """Navigate UK Visa Jobs search results and parse job listings via own-CDP."""
    board = BrowserBoard(id=ID, origin=_ORIGIN, href_pattern=r"/job/", build_urls=_build_urls)
    return run_board(board, query)
