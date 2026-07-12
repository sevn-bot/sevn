"""Extractor registry mapping board ids to their ``run`` callables.

Module: job-ops/scripts/lib/extractors/registry.py

Scope: global + Europe boards only (region-specific non-Europe boards —
seek/AU-NZ, naukri/India, wazzuf/Egypt, fiveamsat/Khamsat — are intentionally omitted).
"""

from __future__ import annotations

from collections.abc import Callable

from ..models import SearchQuery
from .base import ExtractorResult

RunFn = Callable[[SearchQuery], ExtractorResult]


def _registry() -> dict[str, RunFn]:
    from . import (
        adzuna,
        golangjobs,
        gradcracker,
        himalayas,
        hiringcafe,
        jobindex,
        jobnet,
        jobspy_source,
        remoteco,
        remoteok,
        remotive,
        startupjobs,
        ukvisajobs,
        workingnomads,
    )

    return {
        jobspy_source.ID: jobspy_source.run,
        adzuna.ID: adzuna.run,
        hiringcafe.ID: hiringcafe.run,
        workingnomads.ID: workingnomads.run,
        golangjobs.ID: golangjobs.run,
        startupjobs.ID: startupjobs.run,
        jobindex.ID: jobindex.run,
        jobnet.ID: jobnet.run,
        gradcracker.ID: gradcracker.run,
        ukvisajobs.ID: ukvisajobs.run,
        remoteok.ID: remoteok.run,
        remotive.ID: remotive.run,
        himalayas.ID: himalayas.run,
        remoteco.ID: remoteco.run,
    }


def available_sources() -> list[str]:
    """Return the sorted list of registered board ids."""
    return sorted(_registry().keys())


def get_extractor(source: str) -> RunFn | None:
    """Return the ``run`` callable for ``source``, or ``None`` when unknown."""
    return _registry().get(source.strip().lower())


def source_matches(job_source: str, board_id: str) -> bool:
    """Return ``True`` when a stored posting's ``source`` belongs to board ``board_id``.

    For most boards the stored ``source`` equals the board id. The ``jobspy`` board
    fans out to per-site sources (``linkedin``/``indeed``/``glassdoor``), so filtering
    by ``jobspy`` matches any of those (an empty ``board_id`` matches everything).
    """
    board_id = board_id.strip().lower()
    if not board_id or job_source == board_id:
        return True
    if board_id == "jobspy":
        from .jobspy_source import SITES

        return job_source in SITES
    return False
