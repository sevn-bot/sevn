#!/usr/bin/env python3
"""Bundled ``job-ops`` skill — track application status for a stored job.

Updates the operator-managed application lifecycle (status, applied flag/date,
due date, expected salary range, notes, tags, interview log) on a single stored
job identified by its dedupe key, writing back to the JSONL store.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import write_error, write_ok

from lib.models import TRACKING_STATUSES, JobPosting
from lib.settings import content_root_from_env
from lib.store import JobStore


def _append(existing: list[str] | None, value: str) -> list[str]:
    items = list(existing or [])
    if value not in items:
        items.append(value)
    return items


def _apply_updates(job: JobPosting, args: argparse.Namespace) -> None:
    if args.seen:
        job.seen = True
    if args.unseen:
        job.seen = False
    if args.status:
        job.status = args.status
    if args.applied:
        job.applied = True
        if not job.applied_date and args.applied_date:
            job.applied_date = args.applied_date
    if args.applied_date:
        job.applied_date = args.applied_date
    if args.due_date:
        job.due_date = args.due_date
    if args.salary_range:
        job.salary_range = args.salary_range
    if args.note:
        job.notes = _append(job.notes, args.note)
    if args.tag:
        job.tags = _append(job.tags, args.tag)
    if args.interview:
        job.interviews = _append(job.interviews, args.interview)


def main(argv: list[str] | None = None) -> int:
    """Update tracking fields on the stored job identified by ``--key``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True, help="Job dedupe key (from list_jobs.py).")
    parser.add_argument("--seen", action="store_true", help="Mark this job as seen.")
    parser.add_argument("--unseen", action="store_true", help="Clear the seen flag.")
    parser.add_argument("--status", choices=TRACKING_STATUSES, help="Set application status.")
    parser.add_argument("--applied", action="store_true", help="Mark as applied.")
    parser.add_argument("--applied-date", default="", help="Applied date (YYYY-MM-DD).")
    parser.add_argument("--due-date", default="", help="Application/response due date.")
    parser.add_argument("--salary-range", default="", help="Expected salary range.")
    parser.add_argument("--note", default="", help="Append a note.")
    parser.add_argument("--tag", default="", help="Add a tag.")
    parser.add_argument("--interview", default="", help="Append an interview-log entry.")
    args = parser.parse_args(argv)

    store = JobStore(content_root_from_env())
    job = store.get(args.key.strip())
    if job is None:
        write_error(code="NOT_FOUND", error=f"no stored job with key {args.key!r}")
        return 1

    _apply_updates(job, args)
    store.update(job)
    write_ok(
        {
            "key": job.dedupe_key(),
            "title": job.title,
            "seen": job.seen,
            "status": job.status,
            "applied": job.applied,
            "applied_date": job.applied_date,
            "due_date": job.due_date,
            "salary_range": job.salary_range,
            "notes": job.notes or [],
            "tags": job.tags or [],
            "interviews": job.interviews or [],
        },
        message="tracking updated",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
