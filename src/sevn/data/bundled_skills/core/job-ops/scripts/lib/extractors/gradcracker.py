"""Gradcracker extractor (own-CDP browser).

Navigates the public search page with the sevn CDP engine and parses listing
anchors. UK engineering/technology graduate board.
"""

from __future__ import annotations

import httpx

from ..models import SearchQuery
from .base import ExtractorResult
from .browser_board import BrowserBoard, run_board

ID = "gradcracker"
_ORIGIN = "https://www.gradcracker.com"
_SEARCH_PATH = "/search/all-disciplines/engineering-graduate-jobs"
_DEFAULT_TERM = "engineering"


def _build_urls(query: SearchQuery) -> list[str]:
    urls: list[str] = []
    for term in query.search_terms or [_DEFAULT_TERM]:
        urls.append(str(httpx.URL(f"{_ORIGIN}{_SEARCH_PATH}", params={"keywords": term})))
    return urls


def run(query: SearchQuery) -> ExtractorResult:
    """Navigate Gradcracker search results and parse job listings via own-CDP."""
    board = BrowserBoard(id=ID, origin=_ORIGIN, href_pattern=r"/hub/", build_urls=_build_urls)
    return run_board(board, query)
