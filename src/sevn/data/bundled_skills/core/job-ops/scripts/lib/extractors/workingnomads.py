"""Working Nomads extractor (httpx).

Queries the public Working Nomads Elasticsearch search endpoint (remote-only board).
"""

from __future__ import annotations

from typing import Any

from .. import httpclient
from ..models import JobPosting, SearchQuery
from ..text import infer_job_type, matches_search_term
from .base import ExtractorResult

ID = "workingnomads"
_SEARCH_URL = "https://www.workingnomads.com/jobsapi/_search"
_MAX_PAGE_SIZE = 100
_DEFAULT_TERM = "software engineer"


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


def _build_query_string(term: str) -> str:
    trimmed = term.strip()
    if not trimmed:
        return ""
    escaped = trimmed.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _build_request(term: str, results_wanted: int) -> dict[str, Any]:
    request: dict[str, Any] = {
        "size": min(max(results_wanted, 50), _MAX_PAGE_SIZE),
        "_source": [
            "id",
            "slug",
            "title",
            "company",
            "category_name",
            "description",
            "position_type",
            "tags",
            "locations",
            "location_base",
            "pub_date",
            "apply_url",
        ],
        "sort": [{"premium": {"order": "desc"}}, {"pub_date": {"order": "desc"}}],
    }
    query_string = _build_query_string(term)
    if query_string:
        request["query"] = {
            "bool": {
                "must": [
                    {
                        "query_string": {
                            "query": query_string,
                            "fields": ["title^2", "description", "company"],
                        }
                    }
                ]
            }
        }
        request["min_score"] = 2
    return request


def _map(job: dict[str, Any]) -> JobPosting | None:
    raw_id = job.get("id")
    source_job_id = str(raw_id) if isinstance(raw_id, (int, str)) else None
    slug = job.get("slug") if isinstance(job.get("slug"), str) else None
    legacy_url = job.get("url") if isinstance(job.get("url"), str) else None
    if slug:
        job_url = f"https://www.workingnomads.com/jobs/{slug}"
    elif source_job_id:
        job_url = f"https://www.workingnomads.com/job/go/{source_job_id}/"
    elif legacy_url:
        job_url = legacy_url
    else:
        return None

    title = job.get("title") if isinstance(job.get("title"), str) else "Unknown Title"
    description = job.get("description") if isinstance(job.get("description"), str) else None
    location_base = job.get("location_base") if isinstance(job.get("location_base"), str) else None
    locations = _as_str_list(job.get("locations"))
    legacy_location = job.get("location") if isinstance(job.get("location"), str) else None
    location = location_base or legacy_location or (", ".join(locations) if locations else "Remote")
    tags = _as_str_list(job.get("tags"))
    category = job.get("category_name") if isinstance(job.get("category_name"), str) else None
    company = job.get("company") if isinstance(job.get("company"), str) else None
    company_name = job.get("company_name") if isinstance(job.get("company_name"), str) else None
    apply_url = (
        job.get("apply_url")
        if isinstance(job.get("apply_url"), str) and job["apply_url"].strip()
        else job_url
    )
    haystack = f"{title}\n{description or ''}\n{location}\n{', '.join(tags)}"
    return JobPosting(
        source=ID,
        source_job_id=source_job_id,
        title=title,
        employer=company or company_name or "Unknown Employer",
        job_url=job_url,
        application_link=apply_url,
        location=location,
        job_description=description,
        date_posted=job.get("pub_date") if isinstance(job.get("pub_date"), str) else None,
        job_type=infer_job_type(haystack) or "Full-time",
        job_function=category,
        disciplines=", ".join(tags) if tags else category,
        skills=", ".join(tags) if tags else None,
        is_remote=True,
    )


def run(query: SearchQuery) -> ExtractorResult:
    """Query Working Nomads for each term; remote-only boards return empty otherwise."""
    if query.workplace_types and "remote" not in query.workplace_types:
        return ExtractorResult(source=ID, jobs=[])
    terms = query.search_terms or [_DEFAULT_TERM]
    jobs: list[JobPosting] = []
    seen: set[str] = set()
    try:
        for term in terms:
            body = httpclient.post_json(
                _SEARCH_URL, json_body=_build_request(term, query.results_wanted)
            )
            if isinstance(body, list):
                hits = body
            else:
                raw_hits = (body.get("hits") or {}).get("hits") if isinstance(body, dict) else None
                hits = (
                    [h.get("_source") for h in raw_hits if isinstance(h, dict)]
                    if isinstance(raw_hits, list)
                    else []
                )
            found = 0
            for source in hits:
                if not isinstance(source, dict):
                    continue
                if found >= query.results_wanted:
                    break
                if not matches_search_term(
                    f"{source.get('title', '')} {source.get('description', '')}", term
                ):
                    continue
                mapped = _map(source)
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
