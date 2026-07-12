#!/usr/bin/env python3
"""Bundled ``job-ops`` skill (optional) — text-only interview prep per job.

Disabled by default: requires ``--enable``. Produces plain-text/Markdown interview
talking points (STAR+Reflection stories, likely questions, questions to ask) — no
PDF. Uses sevn's configured model tier via the egress proxy; defers to the agent
(``needs_agent_interview_prep``) when unavailable.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import write_error, write_ok

from lib.llm import LlmUnavailable, complete_json
from lib.models import JobPosting, Resume
from lib.settings import content_root_from_env, get_logger
from lib.store import JobStore
from lib.text import prepare_text

_DESC_LIMIT = 2500
_RESUME_LIMIT = 6000


def _bundle(job: JobPosting) -> dict[str, object]:
    return {
        "key": job.dedupe_key(),
        "title": job.title,
        "employer": job.employer,
        "job_url": job.job_url,
        "description": prepare_text(job.job_description, _DESC_LIMIT),
    }


def _prompt(job: JobPosting, resume: Resume) -> str:
    return (
        "You are an interview coach. Using the candidate resume and the job posting, "
        "produce concise interview prep as Markdown text (no PDF, no tables):\n"
        "- 4-6 STAR+Reflection stories mapped to the top job requirements, each "
        "grounded in real resume experience (Situation, Task, Action, Result, "
        "Reflection = what was learned).\n"
        "- Likely interview questions for this role.\n"
        "- Smart questions the candidate should ask.\n"
        "- Any red-flag questions to anticipate and how to frame them.\n"
        'Reply with ONLY a JSON object: {"interview_prep": "<markdown text>"}.\n\n'
        f"### RESUME\n{prepare_text(resume.text, _RESUME_LIMIT)}\n\n"
        f"### JOB\nTitle: {job.title}\nEmployer: {job.employer}\n"
        f"Description:\n{prepare_text(job.job_description, _DESC_LIMIT)}\n"
    )


def _text_from_payload(payload: dict[str, object], field: str) -> str:
    value = payload.get(field, "")
    return value.strip() if isinstance(value, str) else ""


def main(argv: list[str] | None = None) -> int:
    """Draft text-only interview prep for the stored job identified by ``--key``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable", action="store_true", help="Required: opt into generation.")
    parser.add_argument("--key", required=True, help="Job dedupe key (from list_jobs.py).")
    args = parser.parse_args(argv)

    if not args.enable:
        write_error(code="DISABLED", error="off by default; pass --enable to generate")
        return 1

    log = get_logger()
    content_root = content_root_from_env()
    store = JobStore(content_root)
    resume = store.read_resume()
    if not resume.text.strip():
        write_error(code="VALIDATION_ERROR", error="no resume stored; run set_resume.py first")
        return 1
    job = store.get(args.key.strip())
    if job is None:
        write_error(code="NOT_FOUND", error=f"no stored job with key {args.key!r}")
        return 1

    try:
        payload = complete_json(_prompt(job, resume), content_root=content_root, max_tokens=2000)
    except LlmUnavailable as exc:
        log.warning("model tier unavailable ({}); deferring to agent", exc)
        write_ok(
            {
                "needs_agent_interview_prep": True,
                "reason": str(exc),
                "resume": prepare_text(resume.text, _RESUME_LIMIT),
                "job": _bundle(job),
            },
            message="proxy unavailable; tier-B agent should draft this interview prep",
        )
        return 0

    write_ok(
        {
            "key": job.dedupe_key(),
            "title": job.title,
            "interview_prep": _text_from_payload(payload, "interview_prep"),
        },
        message="interview prep drafted",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
