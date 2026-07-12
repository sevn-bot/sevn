"""Triager prompt segment assembly (`specs/13-rlm-triager.md` §3.1, §4.1).

Module: sevn.agent.triager.prompt
Depends: json, sevn.agent.triager.context, sevn.agent.triager.models

Exports:
    Functions:
        build_triager_prompt_segments — four cache-oriented segments §3.1 order.
        concat_prompt_for_stub_llm — join four segments for stub transports.

Note:
    Module-level string constants ``TRIAGER_PROMPT_VERSION`` (semver/hash label
    for traces, §7) and ``GROUP_TRIAGE_INSTRUCTION_V1`` (normative §4.1 English
    block) are part of the public API surface; they are simple assignments and
    are intentionally not listed in ``Exports:`` per the checker's class/function
    inventory rules.
"""

from __future__ import annotations

import json

from sevn.agent.triager.context import RegistryIndexEntry, RegistrySnapshot, TriagePromptContext
from sevn.agent.triager.models import TriageResult
from sevn.prompts.triager import (
    BACK_REFERENCE_RULE as _BACK_REFERENCE_RULE,
)
from sevn.prompts.triager import (
    GROUP_TRIAGE_INSTRUCTION_V1,
    TRIAGER_PROMPT_VERSION,
)
from sevn.prompts.triager import (
    LIVE_FACTUAL_RULE as _LIVE_FACTUAL_RULE,
)
from sevn.prompts.triager import (
    MINIMAL_TOOLSET_RULE as _MINIMAL_TOOLSET_RULE,
)
from sevn.prompts.triager import (
    NO_SILENT_SUBSTITUTION_RULE as _NO_SILENT_SUBSTITUTION_RULE,
)
from sevn.prompts.triager import (
    PLAYWRIGHT_BROWSER_RULE as _PLAYWRIGHT_BROWSER_RULE,
)
from sevn.prompts.triager import (
    PROCESS_INSTALL_RULE as _PROCESS_INSTALL_RULE,
)
from sevn.prompts.triager import (
    REPLAY_PROVIDER_HISTORY_RULE as _REPLAY_PROVIDER_HISTORY_RULE,
)
from sevn.prompts.triager import (
    STATIC_ROLE as _STATIC_ROLE,
)
from sevn.prompts.triager import (
    TOOL_VS_SKILL_RULE as _TOOL_VS_SKILL_RULE,
)
from sevn.prompts.triager import (
    TRUTHFUL_CITATION_RULE as _TRUTHFUL_CITATION_RULE,
)

__all__ = [
    "GROUP_TRIAGE_INSTRUCTION_V1",
    "TRIAGER_PROMPT_VERSION",
    "build_triager_prompt_segments",
    "concat_prompt_for_stub_llm",
]


def _sorted_entries(entries: list[RegistryIndexEntry]) -> list[RegistryIndexEntry]:
    """Sort registry rows by deterministic ASCII-ish name tie-broken by id (`specs/13` §3.1).

    Args:
        entries (list[RegistryIndexEntry]): Unsorted registry rows.

    Returns:
        list[RegistryIndexEntry]: Rows sorted by ``(sort_name, identifier)``.

    Examples:
        >>> a = RegistryIndexEntry(sort_name="b", identifier="b", display_line="b - x")
        >>> b = RegistryIndexEntry(sort_name="a", identifier="a", display_line="a - y")
        >>> [e.identifier for e in _sorted_entries([a, b])]
        ['a', 'b']
    """
    return sorted(entries, key=lambda e: (e.sort_name, e.identifier))


def _registry_segment(snapshot: RegistrySnapshot) -> str:
    """Render the ``[registry]`` cache segment for the Triager prompt.

    Args:
        snapshot (RegistrySnapshot): Materialised tool/skill/MCP slice.

    Returns:
        str: Newline-terminated registry block ready for prompt assembly.

    Examples:
        >>> snap = RegistrySnapshot(registry_version=3)
        >>> out = _registry_segment(snap)
        >>> "registry_version: 3" in out
        True
        >>> out.endswith("\\n")
        True
    """
    tools = _sorted_entries(snapshot.tools)
    skills = _sorted_entries(snapshot.skills)
    mcps = _sorted_entries(snapshot.mcp_servers)
    lines: list[str] = [
        "[registry]",
        f"registry_version: {snapshot.registry_version}",
        f"ADD_CORE_TOOLS_TO_ALL_CONTEXT: {str(snapshot.add_core_tools_to_all_context).lower()}",
        "",
        "[tools]",
        *[t.display_line for t in tools],
        "",
        "[skills]",
        *[s.display_line for s in skills],
        "",
        "[available_skills]",
        *[
            json.dumps(
                {
                    "name": row.name,
                    "summary": row.summary,
                    "scripts": row.scripts,
                    "runnables": row.runnables,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            for row in snapshot.available_skills
        ],
        "",
        "[mcp_servers]",
        *[m.display_line for m in mcps],
    ]
    if snapshot.tools_md_body:
        lines.extend(["", "[TOOLS.md]", snapshot.tools_md_body])
    return "\n".join(lines).strip() + "\n"


def _personality_segment(ctx: TriagePromptContext) -> str:
    """Render the ``[personality]`` segment when allowed by context.

    Args:
        ctx (TriagePromptContext): Per-call suffix inputs (skip flag + markdown).

    Returns:
        str: Personality block, or empty string when omitted.

    Examples:
        >>> ctx = TriagePromptContext(current_message="hi", skip_personality=True)
        >>> _personality_segment(ctx)
        ''
        >>> ctx2 = TriagePromptContext(
        ...     current_message="hi",
        ...     skip_personality=False,
        ...     personality_markdown="SOUL\\n",
        ...     personality_version=2,
        ... )
        >>> "personality_version: 2" in _personality_segment(ctx2)
        True
    """
    if ctx.skip_personality or not (ctx.personality_markdown and ctx.personality_markdown.strip()):
        return ""
    return "\n".join(
        [
            "[personality]",
            f"personality_version: {ctx.personality_version}",
            ctx.personality_markdown.strip(),
            "",
        ],
    )


def _suffix_segment(ctx: TriagePromptContext) -> str:
    """Render the per-call ``[turn_context]`` / transcript / message suffix.

    Args:
        ctx (TriagePromptContext): Per-call suffix slot fillers.

    Returns:
        str: Concatenated suffix segment (already includes trailing newline).

    Examples:
        >>> ctx = TriagePromptContext(current_message="hello")
        >>> out = _suffix_segment(ctx)
        >>> "[current_message]" in out
        True
        >>> "hello" in out
        True
    """
    parts: list[str] = [
        "[turn_context]",
        f"triager_prompt_version: {TRIAGER_PROMPT_VERSION}",
        f"user_language: {ctx.user_language}",
        f"plan_approval.enabled: {str(ctx.plan_approval_enabled).lower()}",
        f"permissions.scope_narrowing.enabled: {str(ctx.permissions_scope_narrowing_enabled).lower()}",
        f"is_first_session: {str(ctx.is_first_session).lower()}",
        f"bootstrap_capture_active: {str(ctx.bootstrap_capture_active).lower()}",
        f"operator_local_date: {ctx.operator_local_date or 'unknown'}",
        "",
        "[transcript]",
        *ctx.transcript_turns,
        "",
        "[lcm_stub]",
        ctx.lcm_summary_stub,
        "",
        "[last_routing]",
        ctx.last_routing_block,
        "",
    ]
    if ctx.inject_group_triage_block:
        parts.extend([GROUP_TRIAGE_INSTRUCTION_V1, ""])
    if ctx.code_orientation_block.strip():
        parts.extend([ctx.code_orientation_block.strip(), ""])
    if ctx.attachment_hints:
        parts.extend(
            [
                "[attachments]",
                json.dumps(ctx.attachment_hints, ensure_ascii=False, sort_keys=True),
                "",
            ],
        )
    parts.extend(["[current_message]", ctx.current_message, ""])
    return "\n".join(parts)


def _static_prefix() -> str:
    """Render the static role + schema prefix block (cache-stable across turns).

    Returns:
        str: ``[static_prefix]`` + ``[triage_schema]`` blob ready to be cached.

    Examples:
        >>> out = _static_prefix()
        >>> "[static_prefix]" in out
        True
        >>> "[triage_schema]" in out
        True
    """
    schema = json.dumps(TriageResult.model_json_schema(), sort_keys=True, indent=2)
    return "\n".join(  # noqa: FLY002
        [
            "[static_prefix]",
            _STATIC_ROLE,
            _TOOL_VS_SKILL_RULE,
            _REPLAY_PROVIDER_HISTORY_RULE,
            _MINIMAL_TOOLSET_RULE,
            _BACK_REFERENCE_RULE,
            _TRUTHFUL_CITATION_RULE,
            _NO_SILENT_SUBSTITUTION_RULE,
            _PROCESS_INSTALL_RULE,
            _PLAYWRIGHT_BROWSER_RULE,
            _LIVE_FACTUAL_RULE,
            "",
            "[triage_schema]",
            schema,
            "",
        ],
    )


def build_triager_prompt_segments(
    *,
    registry_snapshot: RegistrySnapshot,
    triage_context: TriagePromptContext,
) -> tuple[str, str, str, str]:
    """Return four prompt segments in cache-staleness order (`specs/13-rlm-triager.md` §3.1).

    Args:
        registry_snapshot (RegistrySnapshot): Workspace registry slice.
        triage_context (TriagePromptContext): Per-call suffix inputs.

    Returns:
        tuple[str, str, str, str]: ``(static_prefix, registry_block, personality_block, suffix)``.

    Examples:
        >>> snap = RegistrySnapshot(registry_version=1)
        >>> ctx = TriagePromptContext(current_message="hi")
        >>> segs = build_triager_prompt_segments(
        ...     registry_snapshot=snap, triage_context=ctx
        ... )
        >>> len(segs)
        4
        >>> "[static_prefix]" in segs[0]
        True
    """
    static = _static_prefix()
    reg = _registry_segment(registry_snapshot)
    pers = _personality_segment(triage_context)
    suffix = _suffix_segment(triage_context)
    return (static, reg, pers, suffix)


def concat_prompt_for_stub_llm(segments: tuple[str, str, str, str]) -> str:
    """Join segments for transports that accept a single user text blob (stub / dev).

    Args:
        segments (tuple[str, str, str, str]): Output of
            :func:`build_triager_prompt_segments` —
            ``(static, registry, personality, suffix)``.

    Returns:
        str: Segments joined with ``\\n---\\n`` separators, dropping an empty
            personality block when no personality is in play.

    Examples:
        >>> concat_prompt_for_stub_llm(("A", "B", "", "C"))
        'A\\n---\\nB\\n---\\nC'
        >>> concat_prompt_for_stub_llm(("A", "B", "P", "C"))
        'A\\n---\\nB\\n---\\nP\\n---\\nC'
    """
    static, reg, pers, suf = segments
    blocks = [static, reg]
    if pers.strip():
        blocks.append(pers)
    blocks.append(suf)
    return "\n---\n".join(blocks)
