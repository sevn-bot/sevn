"""Remote.co extractor (own-CDP browser) — the board is anti-bot gated.

Remote.co serves category listings at ``/remote-jobs/{category}`` and job detail
pages at ``/job-details/{slug}-{uuid}``. Direct HTTP is blocked, so we navigate with
the sevn CDP engine and parse ``/job-details/`` anchors, mapping each search term to a
category slug.
"""

from __future__ import annotations

import re

from ..models import SearchQuery
from .base import ExtractorResult
from .browser_board import BrowserBoard, run_board

ID = "remoteco"
_ORIGIN = "https://remote.co"
_DEFAULT_TERM = "developer"
_SLUG = re.compile(r"[^a-z0-9]+")


def _slugify(term: str) -> str:
    return _SLUG.sub("-", term.strip().lower()).strip("-")


def _build_urls(query: SearchQuery) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for term in query.search_terms or [_DEFAULT_TERM]:
        slug = _slugify(term) or _DEFAULT_TERM
        url = f"{_ORIGIN}/remote-jobs/{slug}"
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def run(query: SearchQuery) -> ExtractorResult:
    """Navigate Remote.co category listings and parse job links via own-CDP."""
    board = BrowserBoard(
        id=ID, origin=_ORIGIN, href_pattern=r"/job-details/", build_urls=_build_urls
    )
    return run_board(board, query)
