#!/usr/bin/env python3
"""Bundled ``job-ops`` skill — list/filter stored jobs.

Reads ``<content_root>/job-ops/jobs.jsonl`` and emits a filtered, capped view.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import cap_script_row_limit, write_ok

from lib.extractors.registry import source_matches
from lib.models import TRACKING_STATUSES, JobPosting
from lib.store import JobStore


def _matches(
    job: JobPosting,
    *,
    source: str,
    status: str,
    min_score: int | None,
    unscored: bool,
    new_only: bool,
) -> bool:
    if not source_matches(job.source, source):
        return False
    if status and job.status != status:
        return False
    if new_only and job.seen is True:
        return False
    if unscored and job.suitability_score is not None:
        return False
    return not (
        min_score is not None
        and (job.suitability_score is None or job.suitability_score < min_score)
    )


def main(argv: list[str] | None = None) -> int:
    """List stored jobs with optional source/status/score/seen filters."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="", help="Filter by board id.")
    parser.add_argument("--status", choices=TRACKING_STATUSES, help="Filter by tracking status.")
    parser.add_argument("--min-score", type=int, default=None, help="Only jobs scored >= N.")
    parser.add_argument("--unscored", action="store_true", help="Only jobs without a score.")
    parser.add_argument("--new-only", action="store_true", help="Only jobs not yet marked seen.")
    parser.add_argument(
        "--mark-seen", action="store_true", help="Mark the returned jobs as seen after listing."
    )
    parser.add_argument("--limit", type=int, default=20, help="Max rows (1..200).")
    args = parser.parse_args(argv)

    store = JobStore()
    jobs = store.load()
    filtered = [
        j
        for j in jobs
        if _matches(
            j,
            source=args.source.strip(),
            status=args.status or "",
            min_score=args.min_score,
            unscored=args.unscored,
            new_only=args.new_only,
        )
    ]
    filtered.sort(key=lambda j: j.suitability_score or -1, reverse=True)
    limit = cap_script_row_limit(args.limit)
    returned = filtered[:limit]

    marked = 0
    if args.mark_seen and returned:
        marked = store.mark_seen([j.dedupe_key() for j in returned])
        for j in returned:
            j.seen = True

    rows = [j.model_dump(exclude_none=True) for j in returned]

    write_ok(
        {
            "total": len(jobs),
            "matched": len(filtered),
            "returned": len(rows),
            "marked_seen": marked,
            "jobs": rows,
        },
        message=f"{len(filtered)} of {len(jobs)} stored jobs matched",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
