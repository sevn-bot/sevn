"""JobSpy extractor.

Wraps the ``python-jobspy`` library for LinkedIn / Indeed / Glassdoor, scraping one
site at a time with a Glassdoor country-to-city geo fallback.
"""

from __future__ import annotations

from typing import Any

from ..models import JobPosting, SearchQuery
from .base import ExtractorResult

ID = "jobspy"
_DEFAULT_SITES = ["linkedin", "indeed", "glassdoor"]
# Stored `source` values this board fans out to (one per JobSpy site).
SITES = frozenset(_DEFAULT_SITES)
_DEFAULT_TERM = "web developer"

_COUNTRY_ALIASES = {
    "uk": "united kingdom",
    "united kingdom": "united kingdom",
    "us": "united states",
    "usa": "united states",
    "united states": "united states",
    "türkiye": "turkey",
    "czech republic": "czechia",
}
_GLASSDOOR_COUNTRY_TO_CITY = {
    "australia": "Sydney",
    "austria": "Vienna",
    "belgium": "Brussels",
    "brazil": "Sao Paulo",
    "canada": "Toronto",
    "france": "Paris",
    "germany": "Berlin",
    "hong kong": "Hong Kong",
    "india": "Bengaluru",
    "ireland": "Dublin",
    "italy": "Milan",
    "mexico": "Mexico City",
    "netherlands": "Amsterdam",
    "new zealand": "Auckland",
    "singapore": "Singapore",
    "spain": "Madrid",
    "switzerland": "Zurich",
    "united kingdom": "London",
    "united states": "New York",
    "vietnam": "Ho Chi Minh City",
}


def _normalize_country_token(value: str) -> str:
    normalized = " ".join(value.strip().lower().split())
    return _COUNTRY_ALIASES.get(normalized, normalized)


def _is_country_level(location: str, country_indeed: str) -> bool:
    if not location.strip() or not country_indeed.strip():
        return False
    return _normalize_country_token(location) == _normalize_country_token(country_indeed)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return None
    return text


def _num(value: Any) -> float | None:
    try:
        if value is None or str(value).strip().lower() in {"", "nan", "none"}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_jobspy_records(records: list[dict[str, Any]]) -> list[JobPosting]:
    """Map JobSpy DataFrame records into :class:`JobPosting` objects (offline-testable)."""
    jobs: list[JobPosting] = []
    for row in records:
        job_url = _clean(row.get("job_url"))
        if not job_url:
            continue
        jobs.append(
            JobPosting(
                source=_clean(row.get("site")) or ID,
                source_job_id=_clean(row.get("id")),
                job_url=job_url,
                job_url_direct=_clean(row.get("job_url_direct")),
                application_link=_clean(row.get("job_url_direct")) or job_url,
                title=_clean(row.get("title")) or "Unknown Title",
                employer=_clean(row.get("company")) or "Unknown Employer",
                employer_url=_clean(row.get("company_url")),
                location=_clean(row.get("location")),
                date_posted=_clean(row.get("date_posted")),
                job_description=_clean(row.get("description")),
                job_type=_clean(row.get("job_type")),
                salary_min_amount=_num(row.get("min_amount")),
                salary_max_amount=_num(row.get("max_amount")),
                salary_currency=_clean(row.get("currency")),
                salary_interval=_clean(row.get("interval")),
                is_remote=bool(row["is_remote"])
                if isinstance(row.get("is_remote"), bool)
                else None,
                job_level=_clean(row.get("job_level")),
                job_function=_clean(row.get("job_function")),
                company_industry=_clean(row.get("company_industry")),
                company_url_direct=_clean(row.get("company_url_direct")),
                company_logo=_clean(row.get("company_logo")),
                skills=_clean(row.get("skills")),
            )
        )
    return jobs


def _scrape_site(
    scrape_jobs: Any,
    *,
    site: str,
    term: str,
    location: str,
    results_wanted: int,
    hours_old: int,
    country_indeed: str,
    is_remote: bool,
) -> list[dict[str, Any]]:
    kwargs: dict[str, Any] = {
        "site_name": [site],
        "search_term": term,
        "results_wanted": results_wanted,
        "hours_old": hours_old,
        "linkedin_fetch_description": True,
        "is_remote": is_remote,
    }
    if country_indeed.strip():
        kwargs["country_indeed"] = country_indeed
    if location.strip():
        kwargs["location"] = location
    frame = scrape_jobs(**kwargs)
    return list(frame.to_dict("records")) if frame is not None and not frame.empty else []


def run(query: SearchQuery) -> ExtractorResult:
    """Scrape LinkedIn/Indeed/Glassdoor via python-jobspy, one site at a time."""
    try:
        from jobspy import scrape_jobs
    except ImportError:
        return ExtractorResult(
            source=ID,
            success=False,
            error="python-jobspy is not installed; run `uv sync --extra job-ops`",
        )

    terms = query.search_terms or [_DEFAULT_TERM]
    country_indeed = query.country or ""
    location = query.locations[0] if query.locations else ""
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for term in terms:
        for site in _DEFAULT_SITES:
            site_location = location
            if site == "linkedin":
                site_country = ""
            else:
                site_country = country_indeed
                if site == "glassdoor" and _is_country_level(location, country_indeed):
                    fallback = _GLASSDOOR_COUNTRY_TO_CITY.get(
                        _normalize_country_token(country_indeed or location)
                    )
                    if fallback:
                        site_location = fallback
            try:
                records.extend(
                    _scrape_site(
                        scrape_jobs,
                        site=site,
                        term=term,
                        location=site_location if site != "linkedin" else location,
                        results_wanted=query.results_wanted,
                        hours_old=query.hours_old,
                        country_indeed=site_country,
                        is_remote=query.is_remote,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{site}: {exc}")
    if errors and not records:
        return ExtractorResult(source=ID, success=False, error="; ".join(errors))
    return ExtractorResult(source=ID, jobs=normalize_jobspy_records(records))
