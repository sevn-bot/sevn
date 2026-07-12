#!/usr/bin/env python3
"""Bundled ``job-ops`` skill — AI fit-score stored jobs against the operator resume.

Uses sevn's configured model tier via the egress proxy. When the proxy is not
reachable from the skill subprocess, returns a ``needs_agent_scoring`` payload so
the invoking tier-B agent can score the compact job+resume bundle itself.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import cap_script_row_limit, write_error, write_ok

from lib.extractors.registry import source_matches
from lib.llm import LlmUnavailable, complete_json
from lib.models import JobPosting, Resume, ScoreResult
from lib.settings import content_root_from_env, get_logger
from lib.store import JobStore
from lib.text import prepare_text

_DESC_LIMIT = 2000
_RESUME_LIMIT = 6000


def _bundle(job: JobPosting) -> dict[str, object]:
    return {
        "key": job.dedupe_key(),
        "source": job.source,
        "title": job.title,
        "employer": job.employer,
        "location": job.location,
        "job_url": job.job_url,
        "description": prepare_text(job.job_description, _DESC_LIMIT),
    }


def _prompt(job: JobPosting, resume: Resume) -> str:
    return (
        "You are a recruiter-grade job-fit evaluator. Reason about the candidate "
        "resume against the job posting (not keyword matching) and grade fit.\n\n"
        "Assess these dimensions:\n"
        "- MATCH: how the resume covers must-have vs nice-to-have requirements.\n"
        "- KEYWORDS: exact JD skills/tools the resume already evidences vs those missing.\n"
        "- TAILORING: concrete edits to the resume to raise the match for this role.\n"
        "- DEALBREAKERS: hard blockers (location, visa, clearance, seniority, language).\n"
        "- LEGITIMACY: whether the posting reads as a real, active opening or a "
        "ghost/scam job, from description quality and internal contradictions.\n\n"
        "Reply with ONLY a JSON object:\n"
        '{"score": <int 0-100>, '
        '"recommendation": "<strong_fit|good_fit|partial_fit|weak_fit|poor_fit>", '
        '"reason": "<one or two sentences>", '
        '"matched_keywords": ["..."], "missing_keywords": ["..."], '
        '"tailoring_tips": ["..."], "dealbreakers": ["..."], '
        '"legitimacy": "<high_confidence|proceed_with_caution|suspicious>", '
        '"legitimacy_notes": "<one sentence>"}.\n\n'
        f"### RESUME\n{prepare_text(resume.text, _RESUME_LIMIT)}\n\n"
        f"### JOB\nTitle: {job.title}\nEmployer: {job.employer}\n"
        f"Location: {job.location or 'n/a'}\n"
        f"Description:\n{prepare_text(job.job_description, _DESC_LIMIT)}\n"
    )


def _str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _result_from_payload(payload: dict[str, object]) -> ScoreResult:
    """Coerce a raw model JSON payload into a validated :class:`ScoreResult`."""
    try:
        raw_score = int(payload.get("score", 0))  # type: ignore[arg-type]
    except (ValueError, TypeError):
        raw_score = 0
    score = max(0, min(100, raw_score))
    try:
        return ScoreResult.model_validate(
            {
                "score": score,
                "recommendation": str(payload.get("recommendation", "")),
                "reason": str(payload.get("reason", "")),
                "matched_keywords": _str_list(payload.get("matched_keywords")),
                "missing_keywords": _str_list(payload.get("missing_keywords")),
                "tailoring_tips": _str_list(payload.get("tailoring_tips")),
                "dealbreakers": _str_list(payload.get("dealbreakers")),
                "legitimacy": str(payload.get("legitimacy", "")),
                "legitimacy_notes": str(payload.get("legitimacy_notes", "")),
            }
        )
    except (ValueError, TypeError):
        return ScoreResult(score=0, reason="model returned no valid score")


def main(argv: list[str] | None = None) -> int:
    """Score unscored (or all) stored jobs, or emit an agent-scoring fallback."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="", help="Only score jobs from this board id.")
    parser.add_argument("--limit", type=int, default=10, help="Max jobs to score (1..200).")
    parser.add_argument("--rescore", action="store_true", help="Re-score already-scored jobs.")
    parser.add_argument("--dry-run", action="store_true", help="List candidates without scoring.")
    args = parser.parse_args(argv)

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
        if source_matches(j.source, source) and (args.rescore or j.suitability_score is None)
    ][:limit]

    if not candidates:
        write_ok({"scored": 0, "candidates": 0}, message="no jobs to score")
        return 0

    if args.dry_run:
        write_ok(
            {"candidates": [_bundle(j) for j in candidates]},
            message=f"{len(candidates)} candidates",
        )
        return 0

    scored: list[dict[str, object]] = []
    for job in candidates:
        try:
            payload = complete_json(_prompt(job, resume), content_root=content_root)
        except LlmUnavailable as exc:
            log.warning("model tier unavailable ({}); deferring to agent scoring", exc)
            write_ok(
                {
                    "needs_agent_scoring": True,
                    "reason": str(exc),
                    "resume": resume.text[:_RESUME_LIMIT],
                    "jobs": [_bundle(j) for j in candidates],
                },
                message="proxy unavailable; tier-B agent should score these bundles",
            )
            return 0
        result = _result_from_payload(payload)
        job.suitability_score = result.score
        job.suitability_reason = result.reason
        job.suitability_recommendation = result.recommendation or None
        job.matched_keywords = result.matched_keywords or None
        job.missing_keywords = result.missing_keywords or None
        job.tailoring_tips = result.tailoring_tips or None
        job.dealbreakers = result.dealbreakers or None
        job.legitimacy = result.legitimacy or None
        job.legitimacy_notes = result.legitimacy_notes or None
        store.update(job)
        scored.append(
            {
                "key": job.dedupe_key(),
                "title": job.title,
                "score": result.score,
                "recommendation": result.recommendation,
                "reason": result.reason,
                "dealbreakers": result.dealbreakers,
                "legitimacy": result.legitimacy,
            }
        )

    write_ok({"scored": len(scored), "results": scored}, message=f"scored {len(scored)} jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
