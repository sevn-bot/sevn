"""Remotive extractor (httpx) — public JSON API at ``remotive.com/api/remote-jobs``.

Supports server-side keyword search via the ``search`` query parameter.
"""

from __future__ import annotations

from typing import Any

import httpx

from .. import httpclient
from ..models import JobPosting, SearchQuery
from ..text import strip_html
from .base import ExtractorResult

ID = "remotive"
_API_URL = "https://remotive.com/api/remote-jobs"
_DEFAULT_TERM = "software engineer"


def _map(row: dict[str, Any]) -> JobPosting | None:
    job_url = row.get("url") if isinstance(row.get("url"), str) else None
    title = row.get("title") if isinstance(row.get("title"), str) else None
    if not job_url or not title:
        return None
    tags = (
        [t for t in row.get("tags", []) if isinstance(t, str)]
        if isinstance(row.get("tags"), list)
        else []
    )
    description = row.get("description") if isinstance(row.get("description"), str) else None
    location = row.get("candidate_required_location")
    return JobPosting(
        source=ID,
        source_job_id=str(row["id"]) if row.get("id") is not None else None,
        title=title,
        employer=row.get("company_name")
        if isinstance(row.get("company_name"), str)
        else "Unknown Employer",
        job_url=job_url,
        application_link=job_url,
        location=location if isinstance(location, str) and location.strip() else "Remote",
        salary=row.get("salary")
        if isinstance(row.get("salary"), str) and row["salary"].strip()
        else None,
        date_posted=row.get("publication_date")
        if isinstance(row.get("publication_date"), str)
        else None,
        job_description=strip_html(description) if description else None,
        job_type=row.get("job_type") if isinstance(row.get("job_type"), str) else None,
        job_function=row.get("category") if isinstance(row.get("category"), str) else None,
        skills=", ".join(tags) if tags else None,
        company_logo=row.get("company_logo") if isinstance(row.get("company_logo"), str) else None,
        is_remote=True,
    )


def run(query: SearchQuery) -> ExtractorResult:
    """Query Remotive per search term (server-side ``search`` filter)."""
    terms = query.search_terms or [_DEFAULT_TERM]
    limit = min(200, max(1, query.results_wanted))
    jobs: list[JobPosting] = []
    seen: set[str] = set()
    try:
        for term in terms:
            params = {"limit": str(limit)}
            if term:
                params["search"] = term
            url = str(httpx.URL(_API_URL, params=params))
            body = httpclient.get_json(url)
            rows = body.get("jobs") if isinstance(body, dict) else None
            found = 0
            for row in rows if isinstance(rows, list) else []:
                if found >= query.results_wanted or not isinstance(row, dict):
                    break
                mapped = _map(row)
                if mapped is None:
                    continue
                key = mapped.source_job_id or mapped.job_url
                if key in seen:
                    continue
                seen.add(key)
                jobs.append(mapped)
                found += 1
    except Exception as exc:  # noqa: BLE001
        return ExtractorResult(source=ID, success=False, jobs=jobs, error=str(exc))
    return ExtractorResult(source=ID, jobs=jobs)
