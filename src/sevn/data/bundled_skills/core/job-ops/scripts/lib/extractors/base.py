"""Extractor protocol + result type shared by all ``job-ops`` boards.

Module: job-ops/scripts/lib/extractors/base.py

Each extractor takes a normalized :class:`SearchQuery` and returns jobs plus optional
error / Cloudflare-challenge signals so the caller can pause and ask the operator to
solve a challenge headed.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..models import JobPosting, SearchQuery


class ExtractorResult(BaseModel):
    """Outcome of a single extractor run."""

    model_config = ConfigDict(extra="ignore")

    source: str
    success: bool = True
    jobs: list[JobPosting] = Field(default_factory=list)
    error: str | None = None
    challenge_required: str | None = None
    """URL that needs a human to solve a Cloudflare/anti-bot challenge headed."""


class Extractor(Protocol):
    """Common interface implemented by every board extractor."""

    id: str

    def run(self, query: SearchQuery) -> ExtractorResult:
        """Run the extractor for ``query`` and return normalized jobs.

        Args:
            query (SearchQuery): Normalized search request.

        Returns:
            ExtractorResult: Jobs plus error / challenge signals.
        """
        ...
