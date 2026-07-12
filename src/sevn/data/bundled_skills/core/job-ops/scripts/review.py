#!/usr/bin/env python3
"""Bundled ``job-ops`` skill — AI review of the stored operator resume.

Uses sevn's configured model tier via the egress proxy. When the proxy is not
reachable from the skill subprocess, returns a ``needs_agent_review`` payload so
the invoking tier-B agent can review the resume itself.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import write_error, write_ok

from lib.llm import LlmUnavailable, complete_json
from lib.models import Resume, ResumeReview
from lib.settings import content_root_from_env, get_logger
from lib.store import JobStore
from lib.text import prepare_text

_RESUME_LIMIT = 8000
_TARGET_LIMIT = 1200


def _str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _prompt(resume: Resume, target: str) -> str:
    target_block = (
        f"\n### TARGET ROLE / KEYWORDS\n{prepare_text(target, _TARGET_LIMIT)}\n" if target else ""
    )
    return (
        "You are a senior resume reviewer. Critique the resume below for clarity, "
        "impact, and ATS readiness. Prefer concrete, metric-backed bullets; flag "
        "vague claims, buzzwords, and passive voice.\n\n"
        "Reply with ONLY a JSON object:\n"
        '{"overall_score": <int 0-100>, "summary": "<one or two sentences>", '
        '"strengths": ["..."], "weaknesses": ["..."], "suggestions": ["..."], '
        '"missing_keywords": ["..."]}.\n'
        f"{target_block}\n"
        f"### RESUME\n{prepare_text(resume.text, _RESUME_LIMIT)}\n"
    )


def _review_from_payload(payload: dict[str, object]) -> ResumeReview:
    """Coerce a raw model JSON payload into a validated :class:`ResumeReview`."""
    try:
        raw_score = int(payload.get("overall_score", 0))  # type: ignore[arg-type]
    except (ValueError, TypeError):
        raw_score = 0
    score = max(0, min(100, raw_score))
    try:
        return ResumeReview.model_validate(
            {
                "overall_score": score,
                "summary": str(payload.get("summary", "")),
                "strengths": _str_list(payload.get("strengths")),
                "weaknesses": _str_list(payload.get("weaknesses")),
                "suggestions": _str_list(payload.get("suggestions")),
                "missing_keywords": _str_list(payload.get("missing_keywords")),
            }
        )
    except (ValueError, TypeError):
        return ResumeReview(summary="model returned no valid review")


def main(argv: list[str] | None = None) -> int:
    """Review the stored resume, or emit an agent-review fallback."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="", help="Optional target role/JD text to bias review.")
    args = parser.parse_args(argv)

    log = get_logger()
    content_root = content_root_from_env()
    store = JobStore(content_root)
    resume = store.read_resume()
    if not resume.text.strip():
        write_error(code="VALIDATION_ERROR", error="no resume stored; run set_resume.py first")
        return 1

    target = args.target.strip()
    try:
        payload = complete_json(_prompt(resume, target), content_root=content_root, max_tokens=1500)
    except LlmUnavailable as exc:
        log.warning("model tier unavailable ({}); deferring to agent review", exc)
        write_ok(
            {
                "needs_agent_review": True,
                "reason": str(exc),
                "resume": prepare_text(resume.text, _RESUME_LIMIT),
                "target": prepare_text(target, _TARGET_LIMIT),
            },
            message="proxy unavailable; tier-B agent should review this resume",
        )
        return 0

    review = _review_from_payload(payload)
    write_ok(review.model_dump(), message="resume reviewed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
