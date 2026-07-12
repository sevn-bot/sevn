"""hiring.cafe extractor (httpx).

Fetches the Next.js SSR search pages and parses the ``__NEXT_DATA__`` payload.
Falls back to ``challenge_required`` when Cloudflare blocks the request.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .. import httpclient
from ..models import JobPosting, SearchQuery
from ..text import looks_like_challenge
from .base import ExtractorResult

ID = "hiringcafe"
_BASE_URL = "https://hiring.cafe/"
_DEFAULT_TERM = "web developer"
_PAGE_LIMIT = 50
_DATE_PAST_N_DAYS = 30
_NEXT_DATA = re.compile(
    r"<script[^>]*id=[\"']__NEXT_DATA__[\"'][^>]*>\s*([\s\S]*?)\s*</script>",
    re.IGNORECASE,
)

_WORKPLACE_MAP = {"remote": "Remote", "hybrid": "Hybrid", "onsite": "Onsite"}


def _as_record(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _first(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item:
                return item
    return None


def _workplace_types(query: SearchQuery) -> list[str]:
    if not query.workplace_types:
        return ["Remote", "Hybrid", "Onsite"]
    out = [_WORKPLACE_MAP[w] for w in query.workplace_types if w in _WORKPLACE_MAP]
    return out or ["Remote", "Hybrid", "Onsite"]


def _search_state(term: str, workplace_types: list[str]) -> dict[str, Any]:
    return {
        "searchQuery": term,
        "locations": [],
        "workplaceTypes": workplace_types,
        "defaultToUserLocation": False,
        "userLocation": None,
        "dateFetchedPastNDays": _DATE_PAST_N_DAYS,
    }


def _search_url(state: dict[str, Any], page_no: int) -> str:
    params: dict[str, str] = {"searchState": json.dumps(state)}
    if page_no > 0:
        params["page"] = str(page_no)
    return str(httpx.URL(_BASE_URL, params=params))


def _parse_next_data(html: str, url: str) -> dict[str, Any]:
    match = _NEXT_DATA.search(html)
    if not match:
        if looks_like_challenge(html):
            raise httpclient.ChallengeError(url)
        raise ValueError("hiring.cafe response did not include Next.js search data")
    return json.loads(match.group(1) or "")


def _fmt_compensation(processed: dict[str, Any]) -> str | None:
    lo = processed.get("yearly_min_compensation")
    hi = processed.get("yearly_max_compensation")
    lo_n = lo if isinstance(lo, (int, float)) else None
    hi_n = hi if isinstance(hi, (int, float)) else None
    if lo_n is None and hi_n is None:
        return None
    currency = processed.get("listed_compensation_currency")
    frequency = processed.get("listed_compensation_frequency") or "Yearly"
    if lo_n is not None and hi_n is not None:
        amount = f"{round(lo_n)}-{round(hi_n)}"
    elif lo_n is not None:
        amount = f"{round(lo_n)}+"
    else:
        amount = f"{round(hi_n or 0)}"
    parts = [
        p for p in (currency if isinstance(currency, str) else None, amount, f"/ {frequency}") if p
    ]
    return " ".join(parts).strip() or None


def _map(raw: dict[str, Any]) -> JobPosting | None:
    job_info = _as_record(raw.get("job_information")) or {}
    processed = _as_record(raw.get("v5_processed_job_data")) or {}
    company_info = _as_record(job_info.get("company_info")) or {}
    job_url = raw.get("apply_url")
    if not isinstance(job_url, str) or not job_url:
        return None
    source_job_id = next(
        (
            str(raw[k])
            for k in ("id", "objectID", "original_source_id", "requisition_id")
            if isinstance(raw.get(k), (str, int))
        ),
        None,
    )
    title = (
        job_info.get("title")
        or job_info.get("job_title_raw")
        or processed.get("core_job_title")
        or "Unknown Title"
    )
    employer = company_info.get("name") or processed.get("company_name") or "Unknown Employer"
    location = (
        processed.get("formatted_workplace_location")
        or _first(processed.get("workplace_cities"))
        or _first(processed.get("workplace_states"))
        or _first(processed.get("workplace_countries"))
    )
    commitments = (
        processed.get("commitment") if isinstance(processed.get("commitment"), list) else []
    )
    skills = (
        processed.get("technical_tools")
        if isinstance(processed.get("technical_tools"), list)
        else []
    )
    return JobPosting(
        source=ID,
        source_job_id=source_job_id,
        title=title,
        employer=employer,
        job_url=job_url,
        application_link=job_url,
        location=location if isinstance(location, str) else None,
        salary=_fmt_compensation(processed),
        date_posted=processed.get("estimated_publish_date")
        if isinstance(processed.get("estimated_publish_date"), str)
        else None,
        job_description=job_info.get("description") or processed.get("requirements_summary"),
        job_type=", ".join(c for c in commitments if isinstance(c, str)) or None,
        skills=", ".join(s for s in skills if isinstance(s, str)) or None,
        is_remote=processed.get("workplace_type") == "Remote",
    )


def run(query: SearchQuery) -> ExtractorResult:
    """Scrape hiring.cafe SSR search pages for each term."""
    terms = query.search_terms or [_DEFAULT_TERM]
    workplace_types = _workplace_types(query)
    jobs: list[JobPosting] = []
    seen: set[str] = set()
    try:
        for term in terms:
            state = _search_state(term, workplace_types)
            page_no = 0
            collected = 0
            while collected < query.results_wanted and page_no < _PAGE_LIMIT:
                url = _search_url(state, page_no)
                html = httpclient.get_text(url)
                data = _parse_next_data(html, url)
                page_props = _as_record(_as_record((_as_record(data) or {}).get("props")) or {})
                page_props = _as_record((page_props or {}).get("pageProps")) or {}
                hits = (
                    page_props.get("ssrHits") if isinstance(page_props.get("ssrHits"), list) else []
                )
                for raw in hits:
                    if collected >= query.results_wanted or not isinstance(raw, dict):
                        break
                    mapped = _map(raw)
                    if mapped is None:
                        continue
                    key = mapped.source_job_id or mapped.job_url
                    if key in seen:
                        continue
                    seen.add(key)
                    jobs.append(mapped)
                    collected += 1
                if bool(page_props.get("ssrIsLastPage")) or not hits:
                    break
                page_no += 1
    except httpclient.ChallengeError as exc:
        return ExtractorResult(
            source=ID, success=False, jobs=jobs, challenge_required=exc.url, error=str(exc)
        )
    except Exception as exc:  # noqa: BLE001
        return ExtractorResult(source=ID, success=False, jobs=jobs, error=str(exc))
    return ExtractorResult(source=ID, jobs=jobs)
