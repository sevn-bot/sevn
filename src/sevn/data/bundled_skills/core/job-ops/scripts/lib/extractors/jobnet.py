"""Jobnet extractor (own-CDP browser) — Denmark public job board.

Navigates the public Jobnet search with the sevn CDP engine and parses job-detail
anchors. Jobnet's search runs behind the STAR identity server, which issues an
anonymous session to a real browser; when a login wall is returned instead, the
extractor emits ``challenge_required`` so the operator can authenticate once in a
headed session (cookies persist in the CDP profile).
"""

from __future__ import annotations

import re

import httpx

from ..models import JobPosting, SearchQuery
from .base import ExtractorResult
from .browser_board import parse_listing

ID = "jobnet"
_ORIGIN = "https://job.jobnet.dk"
_SEARCH_URL = f"{_ORIGIN}/CV/FindWork/Search"
_HREF_PATTERN = r"/FindWork/(Details|Vis)/"
_DEFAULT_TERM = "software engineer"
_LOGIN_WALL = re.compile(r"STAR Login|identityserver|/Account/Login", re.IGNORECASE)


def _build_urls(query: SearchQuery) -> list[str]:
    country = (query.country or "").strip().lower()
    if country and country not in {"denmark", "dk", "danmark"}:
        return []
    return [
        str(httpx.URL(_SEARCH_URL, params={"SearchString": term}))
        for term in query.search_terms or [_DEFAULT_TERM]
    ]


def run(query: SearchQuery) -> ExtractorResult:
    """Navigate the Jobnet (Denmark) public search via own-CDP and parse listings."""
    from ..browser_fetch import fetch_html

    urls = _build_urls(query)
    if not urls:
        return ExtractorResult(source=ID, jobs=[])
    jobs: list[JobPosting] = []
    seen: set[str] = set()
    try:
        for url in urls:
            if len(jobs) >= query.results_wanted:
                break
            html = fetch_html(url)
            if _LOGIN_WALL.search(html):
                return ExtractorResult(
                    source=ID,
                    success=False,
                    jobs=jobs,
                    challenge_required=url,
                    error="Jobnet login wall; sign in once in a headed browser session and retry",
                )
            for job in parse_listing(html, source=ID, origin=_ORIGIN, href_pattern=_HREF_PATTERN):
                if len(jobs) >= query.results_wanted:
                    break
                if job.job_url in seen:
                    continue
                seen.add(job.job_url)
                jobs.append(job)
    except Exception as exc:  # noqa: BLE001
        return ExtractorResult(source=ID, success=False, jobs=jobs, error=str(exc))
    return ExtractorResult(source=ID, jobs=jobs)
