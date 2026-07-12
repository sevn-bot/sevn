"""Tier-B static instructions must stay description-only (`specs/12-skills-system.md` §10.4)."""

from __future__ import annotations

from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
from sevn.agent.executors.b_harness import _description_only_instructions


def test_description_only_instructions_reject_yaml_fence_markers() -> None:
    """Regression: executor scaffolding must not embed full ``SKILL.md`` bodies."""

    reg = PydanticToolRegistration(
        tool_names=("load_tool", "load_skill"),
        tool_descriptions={"load_tool": "lazy", "load_skill": "lazy"},
        skill_names=("demo",),
        skill_descriptions={
            "demo": "one-line only — not a full manifest",
        },
    )
    text = _description_only_instructions(reg)
    assert "---" not in text
    assert "version:" not in text
    assert "quarantine:" not in text
