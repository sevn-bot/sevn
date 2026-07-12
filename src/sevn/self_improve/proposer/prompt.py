"""Patch author prompt assembly (`specs/33-self-improvement.md` §4.1 stage 5).

Module: sevn.self_improve.proposer.prompt
Depends: json, pathlib

Exports:
    build_patch_author_prompt — user prompt for structured-output patch author.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_patch_author_prompt(
    *,
    job_id: str,
    shortlist: dict[str, Any],
    context_pack: dict[str, Any],
    allowed_globs: list[str],
    deny_globs: list[str] | None,
    plan_md_path: str | None,
    allow_config_changes: bool = False,
    allow_dependency_changes: bool = False,
    allow_lcm_memory_changes: bool = False,
) -> str:
    """Assemble the patch-author user prompt from job artefacts.

    Args:
        job_id (str): Improve job identifier.
        shortlist (dict[str, Any]): Parsed ``shortlist.json`` payload.
        context_pack (dict[str, Any]): Parsed ``context_pack.json`` payload.
        allowed_globs (list[str]): Effective allowlist patterns.
        deny_globs (list[str] | None): Optional deny patterns.
        plan_md_path (str | None): Optional spec-kit plan path.
        allow_config_changes (bool): Whether ``sevn.json`` edits are permitted.
        allow_dependency_changes (bool): Whether dependency manifest edits are permitted.
        allow_lcm_memory_changes (bool): Whether LCM memory paths are permitted.

    Returns:
        str: User prompt text for the structured-output agent.

    Examples:
        >>> text = build_patch_author_prompt(
        ...     job_id="j1",
        ...     shortlist={"candidates": []},
        ...     context_pack={"turn_excerpts": []},
        ...     allowed_globs=["workspace/prompts/**"],
        ...     deny_globs=None,
        ...     plan_md_path=None,
        ... )
        >>> "Allowed globs" in text
        True
    """
    plan_excerpt = ""
    if plan_md_path:
        plan_file = Path(plan_md_path)
        if plan_file.is_file():
            plan_excerpt = plan_file.read_text(encoding="utf-8")[:6000]
    policy_lines = [
        f"- allow_config_changes: {allow_config_changes}",
        f"- allow_dependency_changes: {allow_dependency_changes}",
        f"- allow_lcm_memory_changes: {allow_lcm_memory_changes}",
    ]
    sections = [
        f"# Self-improve patch author — job `{job_id}`",
        "## Task",
        (
            "Propose **one** concrete improvement as a new or edited file under the "
            "allowlisted globs. Return structured output with `target_path` and full "
            "`content` (not a diff). Prefer prompt/skill fixes over code churn."
        ),
        "## Allowed globs",
        "\n".join(f"- `{pattern}`" for pattern in allowed_globs),
        "## Deny globs",
        "\n".join(f"- `{pattern}`" for pattern in (deny_globs or [])) or "- (none configured)",
        "## Policy flags",
        "\n".join(policy_lines),
        "## Shortlist",
        json.dumps(shortlist, indent=2, sort_keys=True)[:8000],
        "## Context pack",
        json.dumps(context_pack, indent=2, sort_keys=True)[:8000],
    ]
    if plan_excerpt:
        sections.extend(["## Spec-kit plan excerpt", plan_excerpt])
    return "\n\n".join(sections)


__all__ = ["build_patch_author_prompt"]
