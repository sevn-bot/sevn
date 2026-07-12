"""Himalayas extractor (httpx) — public JSON API at ``himalayas.app/jobs/api``.

The API is offset-paginated and has no server-side keyword search, so we page
through the most recent postings (bounded) and filter locally per search term.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from .. import httpclient
from ..models import JobPosting, SearchQuery
from ..text import matches_search_term, strip_html
from .base import ExtractorResult

ID = "himalayas"
_API_URL = "https://himalayas.app/jobs/api"
_PAGE_SIZE = 100
_MAX_PAGES = 5


def _epoch_to_iso(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=UTC).isoformat()


def _fmt_salary(row: dict[str, Any]) -> str | None:
    lo = row.get("minSalary")
    hi = row.get("maxSalary")
    lo_n = lo if isinstance(lo, (int, float)) and lo else None
    hi_n = hi if isinstance(hi, (int, float)) and hi else None
    if not lo_n and not hi_n:
        return None
    currency = row.get("currency") if isinstance(row.get("currency"), str) else ""
    period = row.get("salaryPeriod") if isinstance(row.get("salaryPeriod"), str) else ""
    amount = f"{round(lo_n)}-{round(hi_n)}" if lo_n and hi_n else f"{round(lo_n or hi_n)}"
    return " ".join(p for p in (currency, amount, f"/ {period}" if period else "") if p).strip()


def _map(row: dict[str, Any]) -> JobPosting | None:
    job_url = row.get("applicationLink") or row.get("guid")
    title = row.get("title") if isinstance(row.get("title"), str) else None
    if not isinstance(job_url, str) or not job_url or not title:
        return None
    categories = (
        [c for c in row.get("categories", []) if isinstance(c, str)]
        if isinstance(row.get("categories"), list)
        else []
    )
    locations = (
        [loc for loc in row.get("locationRestrictions", []) if isinstance(loc, str)]
        if isinstance(row.get("locationRestrictions"), list)
        else []
    )
    description = row.get("description") if isinstance(row.get("description"), str) else None
    return JobPosting(
        source=ID,
        title=title,
        employer=row.get("companyName")
        if isinstance(row.get("companyName"), str)
        else "Unknown Employer",
        job_url=job_url,
        application_link=job_url,
        location=", ".join(locations) if locations else "Remote",
        salary=_fmt_salary(row),
        date_posted=_epoch_to_iso(row.get("pubDate")),
        job_description=strip_html(description) if description else None,
        job_type=row.get("employmentType") if isinstance(row.get("employmentType"), str) else None,
        disciplines=", ".join(categories) if categories else None,
        skills=", ".join(categories) if categories else None,
        company_logo=row.get("companyLogo")
        if isinstance(row.get("companyLogo"), str) and row["companyLogo"]
        else None,
        is_remote=True,
    )


def run(query: SearchQuery) -> ExtractorResult:
    """Page through recent Himalayas postings and filter locally per term."""
    terms = query.search_terms or [""]
    jobs: list[JobPosting] = []
    seen: set[str] = set()
    try:
        rows: list[dict[str, Any]] = []
        for page in range(_MAX_PAGES):
            url = str(
                httpx.URL(
                    _API_URL, params={"limit": str(_PAGE_SIZE), "offset": str(page * _PAGE_SIZE)}
                )
            )
            body = httpclient.get_json(url)
            chunk = body.get("jobs") if isinstance(body, dict) else None
            page_rows = [r for r in chunk if isinstance(r, dict)] if isinstance(chunk, list) else []
            rows.extend(page_rows)
            if len(page_rows) < _PAGE_SIZE:
                break
        for term in terms:
            found = 0
            for row in rows:
                if found >= query.results_wanted:
                    break
                haystack = (
                    " ".join(str(row.get(k, "")) for k in ("title", "excerpt", "companyName"))
                    + " "
                    + " ".join(str(c) for c in row.get("categories", []) if isinstance(c, str))
                )
                if term and not matches_search_term(haystack, term):
                    continue
                mapped = _map(row)
                if mapped is None:
                    continue
                if mapped.job_url in seen:
                    continue
                seen.add(mapped.job_url)
                jobs.append(mapped)
                found += 1
    except Exception as exc:  # noqa: BLE001
        return ExtractorResult(source=ID, success=False, jobs=jobs, error=str(exc))
    return ExtractorResult(source=ID, jobs=jobs)
