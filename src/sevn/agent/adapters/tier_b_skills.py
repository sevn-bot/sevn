"""Tier-B skills — harness ``Skills`` factory (D7).

Maps triager-scoped operator skills onto pydantic-ai-harness deferred ``Skills``
capabilities while preserving ``sevn_run_skill_script`` dispatch through
``ToolExecutor``.

Module: sevn.agent.adapters.tier_b_skills
Depends: pydantic_ai_harness.skills, sevn.skills.manager

Exports:
    SkillCapabilitySource — skill id + catalog description + SKILL.md body.
    build_harness_skills_capability — harness ``Skills`` with dispatch tools.
    build_tier_b_skill_capabilities — triage-scoped capability list for tier-B.
    resolve_skill_capability_sources — resolve allowlisted skills to metadata rows.
    sevn_run_skill_script — dispatch helper retained for readiness gates.
    skill_capability — build one deferred skill capability (test/helper seam).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pydantic_ai import RunContext  # noqa: TC002 — runtime @cap.tool type resolution
from pydantic_ai.capabilities import (  # noqa: TC002 — runtime capability construction
    AbstractCapability,
    Capability,
)
from pydantic_ai_harness.skills import Skills

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


def _harness_skill_name(sevn_skill_id: str) -> str:
    """Map a sevn skill id to a harness-valid Agent Skill name.

    Args:
        sevn_skill_id (str): Canonical sevn registry skill id.

    Returns:
        str: Harness-safe skill name (underscores become hyphens).

    Examples:
        >>> _harness_skill_name("min_echo")
        'min-echo'
    """
    return sevn_skill_id.replace("_", "-").lower()


def _write_ephemeral_skill_library(
    sources: Sequence[SkillCapabilitySource],
    library: Path,
) -> Path:
    """Materialize harness-valid ``SKILL.md`` packages from resolved sevn metadata.

    Args:
        sources (Sequence[SkillCapabilitySource]): Resolved skill rows for this turn.
        library (Path): Per-turn staging directory (typically a process tempdir).

    Returns:
        Path: Staged skill-library directory passed to harness ``Skills``.

    Examples:
        >>> lib = _write_ephemeral_skill_library(
        ...     [SkillCapabilitySource("pdf", "PDF helpers", "body")],
        ...     Path("/tmp/sevn-harness-skills-abc"),
        ... )
        >>> (lib / "pdf" / "SKILL.md").is_file()
        True
    """
    library.mkdir(parents=True, exist_ok=True)
    for src in sources:
        harness_name = _harness_skill_name(src.skill_id)
        skill_dir = library / harness_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        md_path = skill_dir / "SKILL.md"
        body = "" if src.instructions.strip() == src.description.strip() else src.instructions
        frontmatter = f"---\nname: {harness_name}\ndescription: {src.description}\n---\n\n"
        md_path.write_text(frontmatter + body, encoding="utf-8")
    return library


def _resolve_skill_directories(
    sources: Sequence[SkillCapabilitySource],
) -> tuple[tuple[Path, ...], frozenset[str]]:
    """Stage harness-compatible skill libraries and the triager ``include`` set.

    Args:
        sources (Sequence[SkillCapabilitySource]): Resolved skill rows for this turn.

    Returns:
        tuple[tuple[Path, ...], frozenset[str]]: Library paths and harness include names.

    Examples:
        >>> dirs, include = _resolve_skill_directories(
        ...     [SkillCapabilitySource("pdf", "PDF helpers", "body")],
        ... )
        >>> include
        frozenset({'pdf'})
    """
    library = _write_ephemeral_skill_library(
        sources,
        Path(tempfile.mkdtemp(prefix="sevn-harness-skills-")),
    )
    include = frozenset(_harness_skill_name(src.skill_id) for src in sources)
    return (library,), include


def _remap_capability_ids(
    skills: Skills[BTierDeps],
    sources: Sequence[SkillCapabilitySource],
) -> None:
    """Restore sevn canonical skill ids on harness deferred capabilities.

    Args:
        skills (Skills[BTierDeps]): Harness skills container to rewrite in place.
        sources (Sequence[SkillCapabilitySource]): Resolved sevn skill metadata rows.

    Examples:
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as tmp:
        ...     root = Path(tmp)
        ...     pkg = root / 'pdf'
        ...     pkg.mkdir()
        ...     _ = (pkg / 'SKILL.md').write_text(
        ...         '---\\nname: pdf\\ndescription: d\\n---\\n\\n', encoding='utf-8'
        ...     )
        ...     skills = Skills[BTierDeps](directories=[root], include=['pdf'])
        ...     _remap_capability_ids(skills, [SkillCapabilitySource('pdf', 'd', 'd')])
        ...     skills._deferred_capabilities[0].id
        'pdf'
    """
    sevn_by_harness = {_harness_skill_name(src.skill_id): src.skill_id for src in sources}
    remapped: list[Capability[BTierDeps]] = []
    for cap in skills._deferred_capabilities:
        harness_id = cap.id
        if harness_id is None:
            msg = "harness skill capability missing id"
            raise RuntimeError(msg)
        sevn_id = sevn_by_harness.get(harness_id, harness_id)
        if sevn_id != harness_id:
            object.__setattr__(cap, "id", sevn_id)
        remapped.append(cap)
    object.__setattr__(skills, "_deferred_capabilities", tuple(remapped))


def _bind_run_skill_script_tool(
    cap: Capability[BTierDeps],
    skill_id: str,
) -> None:
    """Register the scoped ``run_skill_script`` tool on one deferred capability.

    Args:
        cap (Capability[BTierDeps]): Harness deferred capability to decorate.
        skill_id (str): Canonical sevn skill id bound by the tool.

    Examples:
        >>> cap = Capability[BTierDeps](id='pdf', description='d', defer_loading=True)
        >>> _bind_run_skill_script_tool(cap, 'pdf')
    """
    tool_name = _skill_run_tool_name(skill_id)

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
        return await sevn_run_skill_script(
            ctx,
            skill=skill_id,
            script=script,
            argv=argv,
        )


def _attach_dispatch_tools(skills: Skills[BTierDeps]) -> None:
    """Add scoped ``run_skill_script`` tools to each harness deferred capability.

    Args:
        skills (Skills[BTierDeps]): Harness skills container to decorate in place.

    Examples:
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as tmp:
        ...     root = Path(tmp)
        ...     pkg = root / 'pdf'
        ...     pkg.mkdir()
        ...     _ = (pkg / 'SKILL.md').write_text(
        ...         '---\\nname: pdf\\ndescription: d\\n---\\n\\n', encoding='utf-8'
        ...     )
        ...     skills = Skills[BTierDeps](directories=[root], include=['pdf'])
        ...     _attach_dispatch_tools(skills)
        ...     len(skills._deferred_capabilities)
        1
    """
    augmented: list[Capability[BTierDeps]] = []
    for cap in skills._deferred_capabilities:
        skill_id = cap.id
        if skill_id is None:
            msg = "harness skill capability missing id"
            raise RuntimeError(msg)
        _bind_run_skill_script_tool(cap, skill_id)
        augmented.append(cap)
    object.__setattr__(skills, "_deferred_capabilities", tuple(augmented))


def build_harness_skills_capability(
    *,
    triage_skills: Sequence[str],
    skill_descriptions: Mapping[str, str],
    skills_manager: SkillsManager | None,
    workspace_path: Path | None = None,
) -> Skills[BTierDeps] | None:
    """Build harness ``Skills`` with sevn ``run_skill_script`` dispatch (D7).

    Args:
        triage_skills (Sequence[str]): Triager-narrowed skill ids for this turn.
        skill_descriptions (Mapping[str, str]): Registered skill summaries from the toolset.
        skills_manager (SkillsManager | None): Optional manager for ``SKILL.md`` bodies.
        workspace_path (Path | None): Retained for call-site compatibility; skill
            packages are staged in a per-turn process tempdir, not under the workspace.

    Returns:
        Skills[BTierDeps] | None: Configured harness capability, or ``None`` when empty.

    Examples:
        >>> cap = build_harness_skills_capability(
        ...     triage_skills=['pdf'],
        ...     skill_descriptions={'pdf': 'PDF helpers'},
        ...     skills_manager=None,
        ...     workspace_path=Path('/tmp'),
        ... )
        >>> cap.__class__.__name__
        'Skills'
    """
    sources = resolve_skill_capability_sources(
        skill_ids=triage_skills,
        skill_descriptions=skill_descriptions,
        skills_manager=skills_manager,
    )
    if not sources:
        return None

    directories, include = _resolve_skill_directories(sources)
    include_order = list(dict.fromkeys(triage_skills))
    include_sorted = [sid for sid in include_order if sid in include]
    skills = Skills[BTierDeps](directories=directories, include=include_sorted)
    _remap_capability_ids(skills, sources)
    _attach_dispatch_tools(skills)
    return skills


def build_tier_b_skill_capabilities(
    *,
    triage_skills: Sequence[str],
    skill_descriptions: Mapping[str, str],
    skills_manager: SkillsManager | None,
    workspace_path: Path | None = None,
) -> list[AbstractCapability[BTierDeps]]:
    """Emit harness ``Skills`` scoped to ``triage.skills[]`` for tier-B assembly.

    Args:
        triage_skills (Sequence[str]): Triager-narrowed skill ids for this turn.
        skill_descriptions (Mapping[str, str]): Registered skill summaries from the toolset.
        skills_manager (SkillsManager | None): Optional manager for ``SKILL.md`` bodies.
        workspace_path (Path | None): Retained for call-site compatibility; skill
            packages are staged in a per-turn process tempdir, not under the workspace.

    Returns:
        list[AbstractCapability[BTierDeps]]: Empty when no skills are listed; otherwise one
            harness ``Skills`` capability wrapping the deferred catalog.

    Examples:
        >>> caps = build_tier_b_skill_capabilities(
        ...     triage_skills=['pdf'],
        ...     skill_descriptions={'pdf': 'PDF helpers'},
        ...     skills_manager=None,
        ...     workspace_path=Path('/tmp'),
        ... )
        >>> caps[0].__class__.__name__
        'Skills'
    """
    skills = build_harness_skills_capability(
        triage_skills=triage_skills,
        skill_descriptions=skill_descriptions,
        skills_manager=skills_manager,
        workspace_path=workspace_path,
    )
    if skills is None:
        return []
    return [cast("AbstractCapability[BTierDeps]", skills)]


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
        ...     skill_ids=['pdf'],
        ...     skill_descriptions={'pdf': 'PDF helpers'},
        ...     skills_manager=None,
        ... )[0].skill_id
        'pdf'
    """
    out: list[SkillCapabilitySource] = []
    for skill_id in dict.fromkeys(skill_ids):
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


def skill_capability(source: SkillCapabilitySource) -> Capability[BTierDeps]:
    """Build one deferred skill capability via harness ``Skills`` (test/helper seam).

    Args:
        source (SkillCapabilitySource): Skill id, catalog line, and ``SKILL.md`` body.

    Returns:
        Capability[BTierDeps]: Native deferred capability for ``Agent(capabilities=...)``.

    Examples:
        >>> cap = skill_capability(SkillCapabilitySource('pdf', 'PDF helpers', 'body'))
        >>> cap.id
        'pdf'
        >>> cap.defer_loading
        True
    """
    if source.description.strip() == "":
        msg = "skill capability requires a non-empty description"
        raise ValueError(msg)
    skills = build_harness_skills_capability(
        triage_skills=[source.skill_id],
        skill_descriptions={source.skill_id: source.description},
        skills_manager=None,
        workspace_path=Path(tempfile.gettempdir()),
    )
    if skills is None:
        msg = f"failed to build harness skill capability for {source.skill_id!r}"
        raise RuntimeError(msg)
    caps = skills._deferred_capabilities
    if len(caps) != 1:
        msg = f"expected one deferred capability for {source.skill_id!r}, got {len(caps)}"
        raise RuntimeError(msg)
    cap = caps[0]
    if source.instructions.strip() != source.description.strip():
        object.__setattr__(
            cap,
            "_instructions",
            [source.instructions],
        )
    return cap


async def sevn_run_skill_script(
    ctx: RunContext[BTierDeps],
    *,
    skill: str,
    script: str,
    argv: Sequence[str] | None = None,
) -> str:
    """Dispatch ``run_skill_script`` through :class:`~sevn.tools.base.ToolExecutor`.

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
    "build_harness_skills_capability",
    "build_tier_b_skill_capabilities",
    "resolve_skill_capability_sources",
    "sevn_run_skill_script",
    "skill_capability",
]
