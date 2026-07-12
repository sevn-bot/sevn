"""Remote OK extractor (httpx) — public JSON API at ``remoteok.com/api``.

The API returns the latest postings as a JSON array whose first element is a legal
notice (Remote OK's ToS asks consumers to link back to the job URL). We fetch once
and filter locally per search term.
"""

from __future__ import annotations

from typing import Any

from .. import httpclient
from ..models import JobPosting, SearchQuery
from ..text import matches_search_term, strip_html
from .base import ExtractorResult

ID = "remoteok"
_API_URL = "https://remoteok.com/api"


def _fmt_salary(row: dict[str, Any]) -> str | None:
    lo = row.get("salary_min")
    hi = row.get("salary_max")
    lo_n = lo if isinstance(lo, (int, float)) and lo else None
    hi_n = hi if isinstance(hi, (int, float)) and hi else None
    if lo_n and hi_n:
        return f"{round(lo_n)}-{round(hi_n)}"
    if lo_n:
        return f"{round(lo_n)}+"
    if hi_n:
        return f"{round(hi_n)}"
    return None


def _map(row: dict[str, Any]) -> JobPosting | None:
    job_url = row.get("url") if isinstance(row.get("url"), str) else None
    position = row.get("position") if isinstance(row.get("position"), str) else None
    if not job_url or not position:
        return None
    tags = (
        [t for t in row.get("tags", []) if isinstance(t, str)]
        if isinstance(row.get("tags"), list)
        else []
    )
    apply_url = (
        row.get("apply_url")
        if isinstance(row.get("apply_url"), str) and row["apply_url"]
        else job_url
    )
    location = (
        row.get("location")
        if isinstance(row.get("location"), str) and row["location"].strip()
        else "Remote"
    )
    description = row.get("description") if isinstance(row.get("description"), str) else None
    return JobPosting(
        source=ID,
        source_job_id=str(row["id"]) if row.get("id") is not None else None,
        title=position,
        employer=row.get("company") if isinstance(row.get("company"), str) else "Unknown Employer",
        job_url=job_url,
        application_link=apply_url,
        location=location,
        salary=_fmt_salary(row),
        date_posted=row.get("date") if isinstance(row.get("date"), str) else None,
        job_description=strip_html(description) if description else None,
        skills=", ".join(tags) if tags else None,
        company_logo=row.get("company_logo") or row.get("logo") or None,
        is_remote=True,
    )


def run(query: SearchQuery) -> ExtractorResult:
    """Fetch the Remote OK feed once, then filter per search term."""
    terms = query.search_terms or [""]
    jobs: list[JobPosting] = []
    seen: set[str] = set()
    try:
        payload = httpclient.get_json(_API_URL)
        rows = (
            [r for r in payload if isinstance(r, dict) and r.get("id")]
            if isinstance(payload, list)
            else []
        )
        for term in terms:
            found = 0
            for row in rows:
                if found >= query.results_wanted:
                    break
                haystack = (
                    " ".join(str(row.get(k, "")) for k in ("position", "description", "company"))
                    + " "
                    + " ".join(str(t) for t in row.get("tags", []) if isinstance(t, str))
                )
                if term and not matches_search_term(haystack, term):
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
