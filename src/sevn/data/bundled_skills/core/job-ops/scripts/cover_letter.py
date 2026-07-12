#!/usr/bin/env python3
"""Bundled ``job-ops`` skill (optional) — draft a text-only cover letter per job.

Disabled by default: requires ``--enable``. Produces a plain-text/Markdown cover
letter (no PDF/LaTeX). Uses sevn's configured model tier via the egress proxy;
defers to the agent (``needs_agent_cover_letter``) when unavailable.
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


def _prompt(job: JobPosting, resume: Resume, tone: str) -> str:
    return (
        "You are a cover-letter writer. Using the candidate resume and the job "
        "posting, draft a concise, tailored cover letter. Mirror key terminology "
        "from the job description, ground every claim in the resume (no invented "
        "experience), use active voice, and avoid buzzwords and em dashes.\n"
        f"Tone: {tone}. Keep it under 350 words. Text only — no PDF, no markdown tables.\n"
        'Reply with ONLY a JSON object: {"cover_letter": "<plain text letter>"}.\n\n'
        f"### RESUME\n{prepare_text(resume.text, _RESUME_LIMIT)}\n\n"
        f"### JOB\nTitle: {job.title}\nEmployer: {job.employer}\n"
        f"Description:\n{prepare_text(job.job_description, _DESC_LIMIT)}\n"
    )


def _text_from_payload(payload: dict[str, object], field: str) -> str:
    value = payload.get(field, "")
    return value.strip() if isinstance(value, str) else ""


def main(argv: list[str] | None = None) -> int:
    """Draft a text-only cover letter for the stored job identified by ``--key``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable", action="store_true", help="Required: opt into generation.")
    parser.add_argument("--key", required=True, help="Job dedupe key (from list_jobs.py).")
    parser.add_argument("--tone", default="professional", help="Desired tone.")
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
        payload = complete_json(
            _prompt(job, resume, args.tone.strip() or "professional"),
            content_root=content_root,
            max_tokens=1500,
        )
    except LlmUnavailable as exc:
        log.warning("model tier unavailable ({}); deferring to agent", exc)
        write_ok(
            {
                "needs_agent_cover_letter": True,
                "reason": str(exc),
                "resume": prepare_text(resume.text, _RESUME_LIMIT),
                "job": _bundle(job),
            },
            message="proxy unavailable; tier-B agent should draft this cover letter",
        )
        return 0

    write_ok(
        {
            "key": job.dedupe_key(),
            "title": job.title,
            "cover_letter": _text_from_payload(payload, "cover_letter"),
        },
        message="cover letter drafted",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
