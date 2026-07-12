"""Pydantic AI adapter surfaces (tier B scaffolding) (`specs/11-tools-registry.md` §2.6).

Produces **description-only** maps plus narrowed shortlists reconciled against
``TriageResult.tools`` / ``TriageResult.skills``. Core meta tools ``load_tool`` and
``load_skill`` bypass the Tier-B cardinality cap whenever ``add_core_tools`` is enabled.

Concrete ``pydantic_ai`` bindings remain in ``specs/14-executor-tier-b.md``.

Module: sevn.agent.adapters.pydantic_adapter
Depends: sevn.agent.triager.models, sevn.config.defaults, sevn.tools.registry

Exports:
    PydanticToolRegistration — payloads executor harnesses bind into planners.
    register_pydantic_tools — build narrowed description rows from ``ToolSet`` + ``TriageResult``.

Examples:
    >>> isinstance(PydanticToolRegistration((), {}, (), {}).tool_names, tuple)
    True
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sevn.config.defaults import DEFAULT_TRIAGER_TIER_B_SKILL_CAP, DEFAULT_TRIAGER_TIER_B_TOOL_CAP

if TYPE_CHECKING:
    from sevn.agent.triager.models import TriageResult
    from sevn.tools.registry import ToolSet


@dataclass(frozen=True)
class PydanticToolRegistration:
    """Serializable subset bound into Pydantic AI agent contexts."""

    tool_names: tuple[str, ...]
    tool_descriptions: Mapping[str, str]
    skill_names: tuple[str, ...]
    skill_descriptions: Mapping[str, str]
    enforce_descriptions_only: bool = True


def _catalog_descriptions(tool_set: ToolSet) -> dict[str, str]:
    """Return descriptions for enabled executor rows (native plus MCP descriptors).

    Args:
        tool_set (ToolSet): Immutable registry snapshot.

    Returns:
        dict[str, str]: Mapping of tool name to one-line description for enabled bundles.

    Examples:
        >>> from sevn.tools.registry import ToolSet
        >>> _catalog_descriptions(ToolSet(1, (), (), {}))
        {}
    """

    rows: MutableMapping[str, str] = {}
    for bundle in [*tool_set.native, *tool_set.mcp]:
        if bundle.enabled:
            rows[bundle.name] = bundle.description
    return dict(rows)


def register_pydantic_tools(
    tool_set: ToolSet,
    triage: Mapping[str, Any] | TriageResult,
    *,
    tier_b_tool_cap: int | None = None,
    tier_b_skill_cap: int | None = None,
    add_core_tools: bool = True,
) -> PydanticToolRegistration:
    """Produce Tier-B scaffolding without importing optional ``pydantic_ai`` binaries.

            Args:
    tool_set (ToolSet): Immutable registry snapshot backing the executor.
    triage (Mapping | TriageResult): Supplies ``tools`` / ``skills`` iterable fields.
    tier_b_tool_cap (int | None): Optional override (defaults PRD/spec value).
    tier_b_skill_cap (int | None): Optional override for skills list.
    add_core_tools (bool): Mirrors ``ADD_CORE_TOOLS_TO_ALL_CONTEXT``.

            Returns:
                PydanticToolRegistration: Narrowed catalogs for adapter binding.

            Examples:
                >>> import json
                >>> from types import SimpleNamespace
                >>> from sevn.tools.base import ToolDefinition
                >>> from sevn.tools.registry import ToolSet
                >>> native = ToolDefinition(
                ...     name="alpha",
                ...     category="meta",
                ...     description="alpha tool",
                ...     parameters={
                ...         "type": "object",
                ...         "properties": {"nested": {"type": "object"}},
                ...     },
                ... )
                >>> ts = ToolSet(9, (native,), (), {})
                >>> triager = SimpleNamespace(tools=("alpha",), skills=())
                >>> reg = register_pydantic_tools(ts, triager, add_core_tools=False)
                >>> "nested" not in json.dumps(dict(reg.tool_descriptions))
                True
    """

    tool_cap = DEFAULT_TRIAGER_TIER_B_TOOL_CAP if tier_b_tool_cap is None else tier_b_tool_cap
    skill_cap = DEFAULT_TRIAGER_TIER_B_SKILL_CAP if tier_b_skill_cap is None else tier_b_skill_cap

    catalog = _catalog_descriptions(tool_set)

    raw_tools = list(triage["tools"]) if isinstance(triage, Mapping) else list(triage.tools)
    raw_skills = list(triage["skills"]) if isinstance(triage, Mapping) else list(triage.skills)

    selected_tools: list[str] = []
    cores: list[str] = []

    if add_core_tools:
        for mandatory in (
            "load_tool",
            "load_skill",
            "run_skill_script",
            "run_skill_runnable",
            "read",
            "edit",
            "write",
            "log_query",
            "list_registry",
        ):
            if mandatory not in catalog or mandatory in cores:
                continue
            cores.append(mandatory)

    extras: list[str] = []
    seen = set(cores)

    for tool_name in raw_tools:
        if tool_name not in catalog or tool_name in seen:
            continue
        seen.add(tool_name)
        extras.append(tool_name)

    # ``tool_cap`` bounds the Triager's emitted tool list (specs/10-schema-ontology.md
    # §5) — the always-on ``cores`` are infrastructure the executor adds on top and must
    # NOT consume that budget. Subtracting ``len(cores)`` zeroed the budget once cores
    # grew to 9 ≥ cap (5), silently dropping every Triager-routed non-core tool (e.g.
    # serp) so it never reached ``allowed_tool_names`` and its calls were filtered out.
    slot_budget = tool_cap
    selected_tools = cores + extras[:slot_budget]
    narrowed_tool_desc = {name: catalog[name] for name in selected_tools if name in catalog}

    selected_skills: list[str] = []
    manifests = dict(tool_set.skill_descriptions)
    for skill_name in raw_skills:
        if skill_name not in manifests:
            continue
        if len(selected_skills) >= skill_cap:
            break
        selected_skills.append(skill_name)

    narrowed_skill_desc = {name: manifests[name] for name in selected_skills}

    return PydanticToolRegistration(
        tool_names=tuple(selected_tools),
        tool_descriptions=narrowed_tool_desc,
        skill_names=tuple(selected_skills),
        skill_descriptions=narrowed_skill_desc,
        enforce_descriptions_only=True,
    )


__all__ = ["PydanticToolRegistration", "register_pydantic_tools"]
