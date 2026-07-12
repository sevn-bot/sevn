"""Adzuna extractor (httpx).

Queries the public Adzuna REST API. Requires ``ADZUNA_APP_ID`` / ``ADZUNA_APP_KEY``.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from .. import httpclient
from ..models import JobPosting, SearchQuery
from .base import ExtractorResult

ID = "adzuna"
_API_BASE = "https://api.adzuna.com/v1/api"
_DEFAULT_TERM = "web developer"


def _fmt_salary(row: dict[str, Any]) -> str | None:
    lo = row.get("salary_min")
    hi = row.get("salary_max")
    lo_n = lo if isinstance(lo, (int, float)) else None
    hi_n = hi if isinstance(hi, (int, float)) else None
    if lo_n is None and hi_n is None:
        return None
    if lo_n is not None and hi_n is not None:
        return f"{round(lo_n)}-{round(hi_n)}"
    if lo_n is not None:
        return f"{round(lo_n)}+"
    return f"{round(hi_n or 0)}"


def _map(row: dict[str, Any]) -> JobPosting | None:
    job_url = row.get("redirect_url")
    if not isinstance(job_url, str) or not job_url:
        return None
    company = row.get("company") if isinstance(row.get("company"), dict) else {}
    location = row.get("location") if isinstance(row.get("location"), dict) else {}
    job_type = " / ".join(
        p for p in (row.get("contract_type"), row.get("contract_time")) if isinstance(p, str) and p
    )
    return JobPosting(
        source=ID,
        source_job_id=str(row["id"]) if row.get("id") is not None else None,
        title=row.get("title") or "Unknown Title",
        employer=company.get("display_name") or "Unknown Employer",
        job_url=job_url,
        application_link=job_url,
        location=location.get("display_name") or None,
        salary=_fmt_salary(row),
        date_posted=row.get("created") or None,
        job_description=row.get("description") or None,
        job_type=job_type or None,
    )


def run(query: SearchQuery) -> ExtractorResult:
    """Query Adzuna for each search term and return normalized postings."""
    app_id = os.environ.get("ADZUNA_APP_ID", "").strip()
    app_key = os.environ.get("ADZUNA_APP_KEY", "").strip()
    if not app_id or not app_key:
        return ExtractorResult(
            source=ID,
            success=False,
            error="Missing Adzuna credentials (ADZUNA_APP_ID / ADZUNA_APP_KEY)",
        )
    country = (query.country or "gb").strip().lower() or "gb"
    where = query.locations[0] if query.locations else None
    terms = query.search_terms or [_DEFAULT_TERM]
    results_per_page = min(50, max(1, query.results_wanted))
    jobs: list[JobPosting] = []
    seen: set[str] = set()
    try:
        for term in terms:
            collected = 0
            page = 1
            while collected < query.results_wanted and page <= 100:
                take = min(results_per_page, query.results_wanted - collected)
                params: dict[str, str] = {
                    "app_id": app_id,
                    "app_key": app_key,
                    "results_per_page": str(take),
                }
                if term:
                    params["what"] = term
                if where:
                    params["where"] = where
                url = httpx.URL(f"{_API_BASE}/jobs/{country}/search/{page}", params=params)
                body = httpclient.get_json(str(url))
                results = body.get("results") if isinstance(body, dict) else None
                rows = results if isinstance(results, list) else []
                mapped_on_page = 0
                for raw in rows:
                    if collected >= query.results_wanted:
                        break
                    if not isinstance(raw, dict):
                        continue
                    mapped = _map(raw)
                    if mapped is None:
                        continue
                    key = mapped.source_job_id or mapped.job_url
                    if key in seen:
                        continue
                    seen.add(key)
                    jobs.append(mapped)
                    collected += 1
                    mapped_on_page += 1
                if len(rows) < take:
                    break
                page += 1
    except Exception as exc:  # noqa: BLE001
        return ExtractorResult(source=ID, success=False, jobs=jobs, error=str(exc))
    return ExtractorResult(source=ID, jobs=jobs)
