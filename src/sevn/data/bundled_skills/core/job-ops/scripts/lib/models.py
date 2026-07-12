"""Pydantic models for the ``job-ops`` skill.

Module: job-ops/scripts/lib/models.py

Normalized search-request and job-posting shapes plus optional AI enrichments,
reduced to the fields this skill uses.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

WorkplaceType = Literal["remote", "hybrid", "onsite"]

TRACKING_STATUSES = (
    "new",
    "interested",
    "applied",
    "interviewing",
    "offer",
    "rejected",
    "archived",
)


class SearchQuery(BaseModel):
    """Normalized search request passed to every extractor."""

    model_config = ConfigDict(extra="ignore")

    search_terms: list[str] = Field(default_factory=list)
    country: str = ""
    locations: list[str] = Field(default_factory=list)
    workplace_types: list[WorkplaceType] = Field(default_factory=list)
    results_wanted: int = 50
    hours_old: int = 168
    is_remote: bool = False


class JobPosting(BaseModel):
    """A normalized job listing plus optional AI enrichments."""

    model_config = ConfigDict(extra="ignore")

    # Source / provenance
    source: str
    source_job_id: str | None = None
    job_url: str
    job_url_direct: str | None = None
    application_link: str | None = None
    date_posted: str | None = None

    # Normalized listing fields
    title: str
    employer: str
    employer_url: str | None = None
    location: str | None = None
    salary: str | None = None
    job_description: str | None = None
    disciplines: str | None = None
    deadline: str | None = None
    degree_required: str | None = None
    starting: str | None = None

    # JobSpy-style optional fields
    job_type: str | None = None
    salary_min_amount: float | None = None
    salary_max_amount: float | None = None
    salary_currency: str | None = None
    salary_interval: str | None = None
    is_remote: bool | None = None
    job_level: str | None = None
    job_function: str | None = None
    company_industry: str | None = None
    company_url_direct: str | None = None
    company_logo: str | None = None
    skills: str | None = None

    # AI enrichments
    suitability_score: int | None = None
    suitability_reason: str | None = None
    suitability_recommendation: str | None = None
    matched_keywords: list[str] | None = None
    missing_keywords: list[str] | None = None
    tailoring_tips: list[str] | None = None
    dealbreakers: list[str] | None = None
    legitimacy: str | None = None
    legitimacy_notes: str | None = None
    tailored_summary: str | None = None
    tailored_headline: str | None = None
    tailored_skills: str | None = None

    # Discovery triage
    first_seen: str | None = None
    seen: bool | None = None

    # Application tracking (operator-managed lifecycle)
    status: str | None = None
    applied: bool | None = None
    applied_date: str | None = None
    due_date: str | None = None
    salary_range: str | None = None
    notes: list[str] | None = None
    tags: list[str] | None = None
    interviews: list[str] | None = None

    def dedupe_key(self) -> str:
        """Return a stable identity key for de-duplication.

        Uses ``(source, source_job_id)`` when an external id is present, otherwise
        ``(source, job_url)``.

        Returns:
            str: A short hash uniquely identifying this posting within a source.
        """
        basis = self.source_job_id.strip() if self.source_job_id else self.job_url.strip()
        digest = hashlib.sha1(f"{self.source}|{basis}".encode()).hexdigest()  # noqa: S324
        return digest[:16]


class ScoreResult(BaseModel):
    """Structured fit-score returned by the LLM scorer.

    Distils a job-fit evaluation into recruiter-style signals: an overall match
    score, a recommendation tier, keyword coverage, tailoring tips, dealbreakers,
    and a posting-legitimacy (ghost-job) assessment.
    """

    model_config = ConfigDict(extra="ignore")

    score: int = Field(ge=0, le=100)
    recommendation: str = ""
    reason: str = ""
    matched_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    tailoring_tips: list[str] = Field(default_factory=list)
    dealbreakers: list[str] = Field(default_factory=list)
    legitimacy: str = ""
    legitimacy_notes: str = ""


class ResumeReview(BaseModel):
    """Structured resume critique returned by the LLM reviewer."""

    model_config = ConfigDict(extra="ignore")

    overall_score: int = Field(ge=0, le=100, default=0)
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)


class Resume(BaseModel):
    """Operator resume/profile used for scoring and tailoring."""

    model_config = ConfigDict(extra="ignore")

    text: str = ""
