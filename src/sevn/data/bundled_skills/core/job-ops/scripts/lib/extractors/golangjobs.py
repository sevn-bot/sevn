"""Golang Jobs extractor (httpx).

Reads the public Supabase REST table backing golangjobs.tech (the site's own public
anon key is used; override with ``GOLANG_JOBS_SUPABASE_ANON_KEY``).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from .. import httpclient
from ..models import JobPosting, SearchQuery
from ..text import matches_search_term, normalize_token
from .base import ExtractorResult

ID = "golangjobs"
_SUPABASE_URL = "https://mvjyjzestmcxxmmmakec.supabase.co"
_DEFAULT_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im12anlqemVzdG1jeHhtbW1ha2Vj"
    "Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM2NDMyNzksImV4cCI6MjA1OTIxOTI3OX0."
    "AEucvhTZofaPFnPmnCMM2ptuE3Iy06_uao4n-6AmEgM"
)
_PAGE_SIZE = 200
_MAX_PAGES = 10
_DEFAULT_TERM = "software engineer"
_SELECT = (
    "id,title,company,type,application_url,slug,posted_at,description,requirements,"
    "cities(name,country)"
)


def _city(row: dict[str, Any]) -> tuple[str | None, str | None]:
    cities = row.get("cities")
    if isinstance(cities, dict):
        name = cities.get("name") if isinstance(cities.get("name"), str) else None
        country = cities.get("country") if isinstance(cities.get("country"), str) else None
        return name, country
    return None, None


def _is_remote(name: str | None) -> bool:
    return normalize_token(name) == "remote"


def _format_location(city: str | None, country: str | None) -> str:
    if _is_remote(city):
        return f"Remote ({country})" if country else "Remote"
    if not city:
        return country or "Unknown location"
    if not country:
        return city
    return f"{city}, {country}"


def _map(row: dict[str, Any]) -> JobPosting | None:
    source_job_id = row.get("id") if isinstance(row.get("id"), str) else None
    slug = row.get("slug") if isinstance(row.get("slug"), str) else None
    if not source_job_id or not slug:
        return None
    city, country = _city(row)
    job_url = f"https://www.golangjobs.tech/golang-jobs/{slug}"
    app_url = row.get("application_url")
    application_link = app_url if isinstance(app_url, str) and app_url.strip() else job_url
    reqs = row.get("requirements")
    skills = (
        ", ".join(r.strip() for r in reqs if isinstance(r, str) and r.strip())
        if isinstance(reqs, list)
        else None
    )
    return JobPosting(
        source=ID,
        source_job_id=source_job_id,
        title=row.get("title") if isinstance(row.get("title"), str) else "Unknown Title",
        employer=row.get("company") if isinstance(row.get("company"), str) else "Unknown Employer",
        job_url=job_url,
        application_link=application_link,
        location=_format_location(city, country),
        date_posted=row.get("posted_at") if isinstance(row.get("posted_at"), str) else None,
        job_description=row.get("description") if isinstance(row.get("description"), str) else None,
        job_type=row.get("type") if isinstance(row.get("type"), str) else None,
        skills=skills or None,
        is_remote=_is_remote(city),
    )


def _fetch_all(anon_key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    headers = {"apikey": anon_key, "authorization": f"Bearer {anon_key}"}
    for page in range(_MAX_PAGES):
        params = {
            "select": _SELECT,
            "is_archived": "eq.false",
            "order": "posted_at.desc",
            "limit": str(_PAGE_SIZE),
            "offset": str(page * _PAGE_SIZE),
        }
        url = httpx.URL(f"{_SUPABASE_URL}/rest/v1/jobs", params=params)
        payload = httpclient.get_json(str(url), headers=headers)
        chunk = payload if isinstance(payload, list) else []
        rows.extend(r for r in chunk if isinstance(r, dict))
        if len(chunk) < _PAGE_SIZE:
            break
    return rows


def run(query: SearchQuery) -> ExtractorResult:
    """Fetch all rows once, then filter per search term."""
    anon_key = os.environ.get("GOLANG_JOBS_SUPABASE_ANON_KEY", "").strip() or _DEFAULT_ANON_KEY
    terms = query.search_terms or [_DEFAULT_TERM]
    jobs: list[JobPosting] = []
    seen: set[str] = set()
    try:
        rows = _fetch_all(anon_key)
        for term in terms:
            found = 0
            for row in rows:
                if found >= query.results_wanted:
                    break
                haystack = " ".join(
                    str(row.get(k, "")) for k in ("title", "company", "description")
                )
                if not matches_search_term(haystack, term):
                    continue
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
