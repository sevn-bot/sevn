"""Regression: Tier-B registrations stay descriptions-only (`specs/11-tools-registry.md` §10.4)."""

from __future__ import annotations

from sevn.agent.adapters.pydantic_adapter import register_pydantic_tools
from sevn.tools.registry import build_session_registry


def _joined_descriptions(reg: object) -> str:
    tool_desc = getattr(reg, "tool_descriptions", {})
    skill_desc = getattr(reg, "skill_descriptions", {})
    parts = list(tool_desc.values()) + list(skill_desc.values())
    return "\n".join(parts)


def test_register_pydantic_tools_avoids_schema_dump_and_skill_paths() -> None:
    """Executor-facing description maps must not embed JSON Schemas or ``SKILL.md`` bodies."""

    triage = {"tools": ("run_skill_script",), "skills": ("lcm",)}
    _executor, tool_set = build_session_registry(registry_version=9)
    reg = register_pydantic_tools(tool_set, triage, tier_b_tool_cap=10, tier_b_skill_cap=7)
    blob = _joined_descriptions(reg)
    assert "SKILL.md" not in blob
    assert '"properties"' not in blob
    assert "$schema" not in blob
