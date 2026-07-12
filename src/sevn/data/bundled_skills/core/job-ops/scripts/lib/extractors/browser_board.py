"""Shared own-CDP browser board scraper for Cloudflare/JS-gated ``job-ops`` boards.

Module: job-ops/scripts/lib/extractors/browser_board.py

Navigates the sevn CDP engine to each board's search URL, parses job-listing
anchors, and returns ``challenge_required`` when an anti-bot wall is detected.
Shared by the JS/Cloudflare-gated boards (gradcracker, ukvisajobs, startupjobs,
remoteco).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from ..models import JobPosting, SearchQuery
from ..text import looks_like_challenge, normalize_whitespace
from .base import ExtractorResult


@dataclass(frozen=True)
class BrowserBoard:
    """Declarative config for an own-CDP browser board."""

    id: str
    origin: str
    href_pattern: str
    build_urls: Callable[[SearchQuery], list[str]]


def parse_listing(html: str, *, source: str, origin: str, href_pattern: str) -> list[JobPosting]:
    """Parse job-listing anchors from rendered board HTML (offline-testable).

    Args:
        html (str): Rendered page HTML.
        source (str): Board id stored on each posting.
        origin (str): Board origin for resolving relative links.
        href_pattern (str): Regex matched against anchor ``href`` values.

    Returns:
        list[JobPosting]: Postings discovered on the page.
    """
    from selectolax.parser import HTMLParser

    pattern = re.compile(href_pattern, re.IGNORECASE)
    tree = HTMLParser(html)
    jobs: list[JobPosting] = []
    seen: set[str] = set()
    for anchor in tree.css("a[href]"):
        href = anchor.attributes.get("href") or ""
        title = normalize_whitespace(anchor.text(deep=True))
        if not href or not title or not pattern.search(href):
            continue
        try:
            job_url = str(httpx.URL(origin).join(href))
        except (ValueError, httpx.InvalidURL):
            continue
        if job_url in seen:
            continue
        seen.add(job_url)
        jobs.append(
            JobPosting(
                source=source,
                title=title,
                employer="Unknown Employer",
                job_url=job_url,
                application_link=job_url,
            )
        )
    return jobs


def run_board(board: BrowserBoard, query: SearchQuery) -> ExtractorResult:
    """Run a browser board: navigate search URLs, parse, and handle challenges."""
    from ..browser_fetch import fetch_html

    jobs: list[JobPosting] = []
    seen: set[str] = set()
    try:
        for url in board.build_urls(query):
            if len(jobs) >= query.results_wanted:
                break
            html = fetch_html(url)
            if looks_like_challenge(html):
                return ExtractorResult(
                    source=board.id,
                    success=False,
                    jobs=jobs,
                    challenge_required=url,
                    error="anti-bot challenge; solve it in a headed browser session and retry",
                )
            for job in parse_listing(
                html, source=board.id, origin=board.origin, href_pattern=board.href_pattern
            ):
                if len(jobs) >= query.results_wanted:
                    break
                if job.job_url in seen:
                    continue
                seen.add(job.job_url)
                jobs.append(job)
    except Exception as exc:  # noqa: BLE001
        return ExtractorResult(source=board.id, success=False, jobs=jobs, error=str(exc))
    return ExtractorResult(source=board.id, jobs=jobs)
