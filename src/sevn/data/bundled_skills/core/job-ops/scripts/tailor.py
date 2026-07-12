#!/usr/bin/env python3
"""Bundled ``job-ops`` skill (optional) — tailor a summary/headline/skills per job.

Disabled by default: requires ``--enable``. Uses sevn's configured model tier via
the egress proxy; defers to the agent (``needs_agent_tailoring``) when unavailable.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import cap_script_row_limit, write_error, write_ok

from lib.extractors.registry import source_matches
from lib.llm import LlmUnavailable, complete_json
from lib.models import JobPosting, Resume
from lib.settings import content_root_from_env, get_logger
from lib.store import JobStore

_DESC_LIMIT = 2000
_RESUME_LIMIT = 6000


def _bundle(job: JobPosting) -> dict[str, object]:
    return {
        "key": job.dedupe_key(),
        "title": job.title,
        "employer": job.employer,
        "job_url": job.job_url,
        "description": (job.job_description or "")[:_DESC_LIMIT],
    }


def _prompt(job: JobPosting, resume: Resume) -> str:
    return (
        "You are a CV tailoring assistant. Given a resume and a job posting, produce "
        "a tailored application summary, a one-line headline, and a comma-separated "
        "skills list emphasising the most relevant strengths for this role.\n"
        'Reply with ONLY a JSON object: {"summary": "<text>", "headline": "<text>", '
        '"skills": "<comma-separated>"}.\n\n'
        f"### RESUME\n{resume.text[:_RESUME_LIMIT]}\n\n"
        f"### JOB\nTitle: {job.title}\nEmployer: {job.employer}\n"
        f"Description:\n{(job.job_description or '')[:_DESC_LIMIT]}\n"
    )


def main(argv: list[str] | None = None) -> int:
    """Generate tailored fields for selected stored jobs (opt-in)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable", action="store_true", help="Required: opt into tailoring.")
    parser.add_argument("--source", default="", help="Only tailor jobs from this board id.")
    parser.add_argument("--limit", type=int, default=5, help="Max jobs to tailor (1..200).")
    parser.add_argument("--retailor", action="store_true", help="Re-tailor already-tailored jobs.")
    args = parser.parse_args(argv)

    if not args.enable:
        write_error(code="DISABLED", error="tailoring is off by default; pass --enable to run it")
        return 1

    log = get_logger()
    content_root = content_root_from_env()
    store = JobStore(content_root)
    resume = store.read_resume()
    if not resume.text.strip():
        write_error(code="VALIDATION_ERROR", error="no resume stored; run set_resume.py first")
        return 1

    source = args.source.strip()
    limit = cap_script_row_limit(args.limit)
    candidates = [
        j
        for j in store.load()
        if source_matches(j.source, source) and (args.retailor or j.tailored_summary is None)
    ][:limit]

    if not candidates:
        write_ok({"tailored": 0, "candidates": 0}, message="no jobs to tailor")
        return 0

    tailored: list[dict[str, object]] = []
    for job in candidates:
        try:
            payload = complete_json(
                _prompt(job, resume), content_root=content_root, max_tokens=1500
            )
        except LlmUnavailable as exc:
            log.warning("model tier unavailable ({}); deferring to agent tailoring", exc)
            write_ok(
                {
                    "needs_agent_tailoring": True,
                    "reason": str(exc),
                    "resume": resume.text[:_RESUME_LIMIT],
                    "jobs": [_bundle(j) for j in candidates],
                },
                message="proxy unavailable; tier-B agent should tailor these bundles",
            )
            return 0
        job.tailored_summary = str(payload.get("summary", "")) or None
        job.tailored_headline = str(payload.get("headline", "")) or None
        job.tailored_skills = str(payload.get("skills", "")) or None
        store.update(job)
        tailored.append(
            {"key": job.dedupe_key(), "title": job.title, "headline": job.tailored_headline}
        )

    write_ok(
        {"tailored": len(tailored), "results": tailored}, message=f"tailored {len(tailored)} jobs"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
