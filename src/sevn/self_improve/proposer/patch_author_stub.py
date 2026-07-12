"""Deterministic patch author stub for hermetic CI (`specs/33-self-improvement.md` §4.1).

Module: sevn.self_improve.proposer.patch_author_stub
Depends: difflib, json, pathlib, sevn.self_improve.proposer.patch_author

Exports:
    stub_author_patch_from_shortlist — JSON metadata diff without LLM calls.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from sevn.self_improve.proposer.patch_author import (
    PatchAuthorResult,
    _deterministic_target_path,
    _resolve_allowed_globs,
    _shortlist_summary,
    reject_patch_glob_scope,
)


def stub_author_patch_from_shortlist(
    *,
    job_id: str,
    shortlist: dict[str, Any],
    allowed_globs: list[str] | None = None,
    deny_globs: list[str] | None = None,
    plan_md_path: str | None = None,
) -> PatchAuthorResult:
    """Build a minimal unified diff documenting shortlist metadata (no LLM).

    Args:
        job_id (str): Improve job identifier (stable slug input).
        shortlist (dict[str, Any]): Parsed ``shortlist.json`` payload.
        allowed_globs (list[str] | None): Optional allowlist; defaults to PRD presets.
        deny_globs (list[str] | None): Optional deny patterns.
        plan_md_path (str | None): Optional spec-kit ``plan.md`` path for prompt context.

    Returns:
        PatchAuthorResult: ``ok=True`` with diff text, or ``ok=False`` with ``rejection``.

    Examples:
        >>> result = stub_author_patch_from_shortlist(
        ...     job_id="job-abc",
        ...     shortlist={"candidates": []},
        ... )
        >>> result.ok and "seimprove" in (result.target_path or "")
        True
    """
    globs = _resolve_allowed_globs(allowed_globs)
    target = _deterministic_target_path(job_id=job_id, allowed_globs=globs)
    if target is None:
        return PatchAuthorResult(
            ok=False,
            diff="",
            target_path=None,
            rejection="patch_rejected_scope: no target path under allowed_globs",
        )
    summary = _shortlist_summary(shortlist)
    plan_excerpt: str | None = None
    if plan_md_path:
        plan_file = Path(plan_md_path)
        if plan_file.is_file():
            plan_excerpt = plan_file.read_text(encoding="utf-8")[:4000]
    body = {
        "job_id": job_id,
        "schema_version": 1,
        "kind": "self_improve_deterministic_stub",
        "shortlist": summary,
        "spec_kit_plan_path": plan_md_path,
        "spec_kit_plan_excerpt": plan_excerpt,
    }
    text = json.dumps(body, indent=2, sort_keys=True) + "\n"
    new_lines = text.splitlines(keepends=True)
    diff = "".join(
        difflib.unified_diff(
            [],
            new_lines,
            fromfile="/dev/null",
            tofile=target,
            lineterm="\n",
        )
    )
    scope_reason = reject_patch_glob_scope(diff, allowed_globs=globs, deny_globs=deny_globs)
    if scope_reason is not None:
        return PatchAuthorResult(ok=False, diff=diff, target_path=target, rejection=scope_reason)
    from sevn.self_improve.proposer import reject_patch_diff

    security_reason = reject_patch_diff(diff)
    if security_reason is not None:
        return PatchAuthorResult(ok=False, diff=diff, target_path=target, rejection=security_reason)
    return PatchAuthorResult(ok=True, diff=diff, target_path=target, rejection=None)


__all__ = ["stub_author_patch_from_shortlist"]
