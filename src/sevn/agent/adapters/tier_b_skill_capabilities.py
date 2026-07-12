"""Defer-loading skill capabilities for tier-B (W6 / W15 native).

Each operator skill the Triager lists becomes a native ``Capability(defer_loading=True)``
whose instructions come from ``SKILL.md`` and whose tool calls ``sevn_run_skill_script``.

Module: sevn.agent.adapters.tier_b_skill_capabilities
Depends: pydantic_ai, sevn.agent.executors.b_types, sevn.skills.manager

Exports:
    SkillCapabilitySource — skill id + catalog description + SKILL.md body.
    skill_capability — build one deferred skill capability.
    build_tier_b_skill_capabilities — triage-scoped capability list for W6.2.
    resolve_skill_capability_sources — resolve allowlisted skills to metadata rows.
    sevn_run_skill_script — dispatch helper retained for readiness gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic_ai import RunContext  # noqa: TC002 — runtime @cap.tool type resolution
from pydantic_ai.capabilities import AbstractCapability, Capability

from sevn.agent.executors.b_types import BTierDeps
from sevn.skills.errors import SkillExecutionError
from sevn.tools.base import ToolCall

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sevn.skills.manager import SkillsManager


@dataclass(frozen=True)
class SkillCapabilitySource:
    """Resolved skill metadata for one deferred capability."""

    skill_id: str
    description: str
    instructions: str


def _skill_run_tool_name(skill_id: str) -> str:
    """Return the scoped pydantic-ai tool name for one skill's script runner.

    Args:
        skill_id (str): Canonical skill id from the triager allowlist.

    Returns:
        str: Unique tool name stable for history replay.

    Examples:
        >>> _skill_run_tool_name("pdf")
        'pdf__run_skill_script'
    """
    return f"{skill_id}__run_skill_script"


def skill_capability(source: SkillCapabilitySource) -> Capability[BTierDeps]:
    """Build one native ``defer_loading`` skill capability (W6.1 / W15.3).

    Args:
        source (SkillCapabilitySource): Skill id, catalog line, and SKILL.md body.

    Returns:
        Capability[BTierDeps]: Native deferred capability for ``Agent(capabilities=...)``.

    Examples:
        >>> cap = skill_capability(SkillCapabilitySource("pdf", "PDF helpers", "body"))
        >>> cap.id
        'pdf'
        >>> cap.defer_loading
        True
    """
    skill_id = source.skill_id
    tool_name = _skill_run_tool_name(skill_id)
    cap = Capability[BTierDeps](
        id=skill_id,
        description=source.description,
        instructions=source.instructions,
        defer_loading=True,
    )

    @cap.tool(
        name=tool_name,
        description=(
            f"Execute a script step for the `{skill_id}` skill (scoped run_skill_script facade)."
        ),
    )
    async def run_skill_script(
        ctx: RunContext[BTierDeps],
        script: str,
        argv: list[str] | None = None,
    ) -> str:
        """Execute a declared script for this skill via ToolExecutor."""
        return await sevn_run_skill_script(
            ctx,
            skill=skill_id,
            script=script,
            argv=argv,
        )

    return cap


def resolve_skill_capability_sources(
    *,
    skill_ids: Sequence[str],
    skill_descriptions: Mapping[str, str],
    skills_manager: SkillsManager | None,
) -> list[SkillCapabilitySource]:
    """Resolve triager-listed skills into capability metadata rows.

    Args:
        skill_ids (Sequence[str]): ``TriageResult.skills`` allowlist for this turn.
        skill_descriptions (Mapping[str, str]): Session ``ToolSet`` skill summaries.
        skills_manager (SkillsManager | None): Optional manager for full ``SKILL.md`` bodies.

    Returns:
        list[SkillCapabilitySource]: One row per allowlisted skill present in the registry.

    Examples:
        >>> resolve_skill_capability_sources(
        ...     skill_ids=["pdf"],
        ...     skill_descriptions={"pdf": "PDF helpers"},
        ...     skills_manager=None,
        ... )[0].skill_id
        'pdf'
    """
    out: list[SkillCapabilitySource] = []
    for skill_id in sorted(dict.fromkeys(skill_ids)):
        description = skill_descriptions.get(skill_id, "").strip()
        if not description:
            continue
        instructions = description
        if skills_manager is not None:
            try:
                rec = skills_manager.get_record(skill_id)
            except SkillExecutionError:
                pass
            else:
                body = rec.markdown_raw.strip()
                instructions = body if body else rec.manifest.description
        out.append(
            SkillCapabilitySource(
                skill_id=skill_id,
                description=description,
                instructions=instructions,
            ),
        )
    return out


def build_tier_b_skill_capabilities(
    *,
    triage_skills: Sequence[str],
    skill_descriptions: Mapping[str, str],
    skills_manager: SkillsManager | None,
) -> list[AbstractCapability[BTierDeps]]:
    """Emit deferred skill capabilities scoped to ``triage.skills[]`` (W6.2 / W15.3).

    The framework injects ``load_capability`` when any deferred capability is present.

    Args:
        triage_skills (Sequence[str]): Triager-narrowed skill ids for this turn.
        skill_descriptions (Mapping[str, str]): Registered skill summaries.
        skills_manager (SkillsManager | None): Optional manager for ``SKILL.md`` bodies.

    Returns:
        list[AbstractCapability[BTierDeps]]: Empty when no skills are listed; otherwise one
            native deferred capability per listed skill.

    Examples:
        >>> build_tier_b_skill_capabilities(
        ...     triage_skills=["pdf"],
        ...     skill_descriptions={"pdf": "PDF helpers", "graphify": "graphs"},
        ...     skills_manager=None,
        ... )[0].id
        'pdf'
    """
    sources = resolve_skill_capability_sources(
        skill_ids=triage_skills,
        skill_descriptions=skill_descriptions,
        skills_manager=skills_manager,
    )
    return [skill_capability(src) for src in sources]


async def sevn_run_skill_script(
    ctx: RunContext[BTierDeps],
    *,
    skill: str,
    script: str,
    argv: Sequence[str] | None = None,
) -> str:
    """Dispatch ``run_skill_script`` through :class:`~sevn.tools.base.ToolExecutor` (W6.1).

    Readiness and ``requires_env`` gates remain in the registry handler — capabilities
    do not bypass them.

    Args:
        ctx (RunContext[BTierDeps]): Pydantic AI run context carrying tier-B deps.
        skill (str): Canonical skill id bound by the deferred capability.
        script (str): Manifest-declared script path.
        argv (Sequence[str] | None): Optional positional argv for the script.

    Returns:
        str: Raw §3.1 JSON envelope string from the executor.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(sevn_run_skill_script)
        True
    """
    payload = {
        "skill": skill,
        "script": script,
        "argv": [str(a) for a in (argv or ())],
    }
    return await ctx.deps.tool_executor.dispatch(
        ctx.deps.effective_tool_context(),
        ToolCall(name="run_skill_script", arguments=payload),
    )


__all__ = [
    "SkillCapabilitySource",
    "build_tier_b_skill_capabilities",
    "resolve_skill_capability_sources",
    "sevn_run_skill_script",
    "skill_capability",
]
