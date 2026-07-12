"""Jobindex extractor (httpx) — Denmark board.

Parses the ``var Stash = {…}`` bootstrap JSON embedded in the public search HTML.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from .. import httpclient
from ..models import JobPosting, SearchQuery
from ..text import strip_html
from .base import ExtractorResult

ID = "jobindex"
_BASE_URL = "https://www.jobindex.dk"
_SEARCH_URL = f"{_BASE_URL}/jobsoegning"
_MAX_PAGES = 50
_DEFAULT_TERM = "software engineer"


def _abs_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(httpx.URL(_BASE_URL).join(value))
    except (ValueError, httpx.InvalidURL):
        return None


def _get_str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _extract_store_data(html: str) -> dict[str, Any]:
    start = html.find("var Stash =")
    if start < 0:
        raise ValueError("Jobindex Stash payload was not found")
    json_start = html.find("{", start)
    if json_start < 0:
        raise ValueError("Jobindex Stash JSON start was not found")
    script_end = html.find("</script>", json_start)
    if script_end < 0:
        raise ValueError("Jobindex Stash script end was not found")
    json_text = html[json_start:script_end].strip().rstrip(";").strip()
    stash = json.loads(json_text)
    store_data = (stash.get("jobsearch/result_app") or {}).get("storeData")
    if not isinstance(store_data, dict):
        raise ValueError("Jobindex storeData payload was not found")
    return store_data


def _map(result: dict[str, Any]) -> JobPosting | None:
    source_job_id = _get_str(result.get("tid"))
    job_url = _abs_url(_get_str(result.get("share_url"))) or _abs_url(_get_str(result.get("url")))
    if not source_job_id or not job_url:
        return None
    company = result.get("workplace_company") or result.get("company") or {}
    company = company if isinstance(company, dict) else {}
    addresses = result.get("addresses") if isinstance(result.get("addresses"), list) else []
    first_addr = addresses[0] if addresses and isinstance(addresses[0], dict) else {}
    area = _get_str(result.get("area"))
    location = _get_str(first_addr.get("simple_string")) or _get_str(first_addr.get("city")) or area
    employer = (
        _get_str(result.get("companytext")) or _get_str(company.get("name")) or "Unknown Employer"
    )
    html_snippet = _get_str(result.get("html"))
    return JobPosting(
        source=ID,
        source_job_id=source_job_id,
        title=_get_str(result.get("headline")) or "Unknown Title",
        employer=employer,
        employer_url=_abs_url(_get_str(company.get("homeurl"))),
        job_url=job_url,
        job_url_direct=_abs_url(_get_str(result.get("url"))),
        application_link=_abs_url(_get_str(result.get("app_apply_url")))
        or _abs_url(_get_str(result.get("apply_url")))
        or job_url,
        location=location,
        date_posted=_get_str(result.get("firstdate")),
        deadline=_get_str(result.get("apply_deadline")) or _get_str(result.get("lastdate")),
        job_description=strip_html(html_snippet) if html_snippet else None,
        is_remote=result.get("home_workplace")
        if isinstance(result.get("home_workplace"), bool)
        else None,
        company_logo=_abs_url(_get_str(result.get("listlogo_url")))
        or _abs_url(_get_str(company.get("logo"))),
        company_url_direct=_abs_url(_get_str(company.get("homeurl"))),
    )


def _fetch_search_response(term: str, page: int) -> dict[str, Any]:
    params = {"q": term}
    if page > 1:
        params["page"] = str(page)
    url = httpx.URL(_SEARCH_URL, params=params)
    html = httpclient.get_text(str(url), headers={"accept-language": "en-US,en;q=0.9,da;q=0.8"})
    search_response = _extract_store_data(html).get("searchResponse")
    if not isinstance(search_response, dict):
        raise ValueError("Jobindex searchResponse payload was not found")
    return search_response


def run(query: SearchQuery) -> ExtractorResult:
    """Query Jobindex (Denmark board); returns empty for non-Danish countries."""
    country = (query.country or "").strip().lower()
    if country and country not in {"denmark", "dk", "danmark"}:
        return ExtractorResult(source=ID, jobs=[])
    terms = query.search_terms or [_DEFAULT_TERM]
    jobs: list[JobPosting] = []
    seen: set[str] = set()
    try:
        for term in terms:
            found = 0
            page_total = 1
            page = 1
            while page <= page_total and found < query.results_wanted:
                response = _fetch_search_response(term, page)
                results = (
                    response.get("results") if isinstance(response.get("results"), list) else []
                )
                raw_total = response.get("total_pages")
                total = (
                    int(raw_total)
                    if isinstance(raw_total, (int, str)) and str(raw_total).isdigit()
                    else 1
                )
                page_total = min(max(total, 1), _MAX_PAGES)
                for raw in results:
                    if found >= query.results_wanted or not isinstance(raw, dict):
                        break
                    mapped = _map(raw)
                    if mapped is None:
                        continue
                    key = mapped.source_job_id or mapped.job_url
                    if key in seen:
                        continue
                    seen.add(key)
                    jobs.append(mapped)
                    found += 1
                page += 1
    except Exception as exc:  # noqa: BLE001
        return ExtractorResult(source=ID, success=False, jobs=jobs, error=str(exc))
    return ExtractorResult(source=ID, jobs=jobs)
