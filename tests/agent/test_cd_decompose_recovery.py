"""Tier-C/D decompose parse tolerance for open models (`specs/21-executor-tier-cd.md`).

MiniMax-M3 intermittently emits ``{}`` or unrelated JSON into the decompose slot.
The harness must coerce a missing-``steps`` object into a single-step plan rather
than surfacing a raw parser error.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from sevn.agent.executors.cd_harness import (
    _coerce_json_object,
    _decompose_has_usable_steps,
    _wrap_decompose_as_single_step,
)
from sevn.agent.executors.cd_types import Plan
from sevn.agent.triager.models import ComplexityTier
from sevn.tools.registry import ToolSet


def _tool_set() -> ToolSet:
    return ToolSet(native=(), mcp=(), registry_version=7, skill_descriptions={})


def _triage_c() -> MagicMock:
    tr = MagicMock()
    tr.complexity = ComplexityTier.C
    return tr


def test_has_usable_steps_detects_nonempty_list() -> None:
    assert _decompose_has_usable_steps({"steps": [{"id": "1", "title": "t"}]})
    assert not _decompose_has_usable_steps({"steps": []})
    assert not _decompose_has_usable_steps({})
    assert not _decompose_has_usable_steps({"steps": "nope"})


def test_coerce_tolerates_fenced_and_prose_json() -> None:
    assert _coerce_json_object('```json\n{"steps": [1]}\n```') == {"steps": [1]}
    assert _coerce_json_object('Here is the plan:\n{"steps": []}\nDone.') == {"steps": []}
    assert _coerce_json_object("not json at all") == {}


def test_wrap_bare_object_becomes_single_step_plan() -> None:
    """An unrelated object (no steps) wraps to a one-step plan from the task text."""
    out = _wrap_decompose_as_single_step(
        {"thumbs_up": True, "thumbs_down": False},
        triage=_triage_c(),
        incoming_text="all this needs to be fixed",
        tool_set=_tool_set(),
    )
    assert out is not None
    plan = Plan.model_validate(out)
    assert len(plan.steps) == 1
    assert plan.steps[0].title == "all this needs to be fixed"
    assert plan.meta.complexity == "C"
    assert plan.meta.registry_version == 7


def test_wrap_empty_object_uses_incoming_text() -> None:
    out = _wrap_decompose_as_single_step(
        {},
        triage=_triage_c(),
        incoming_text="summarize the report",
        tool_set=_tool_set(),
    )
    assert out is not None
    plan = Plan.model_validate(out)
    assert plan.steps[0].title == "summarize the report"


def test_wrap_returns_none_without_task_text() -> None:
    """No task text and no usable summary → unrecoverable (caller surfaces failure)."""
    assert (
        _wrap_decompose_as_single_step(
            {},
            triage=_triage_c(),
            incoming_text="   ",
            tool_set=_tool_set(),
        )
        is None
    )


def test_wrap_falls_back_to_summary_when_text_blank() -> None:
    out = _wrap_decompose_as_single_step(
        {"summary": "do the thing"},
        triage=_triage_c(),
        incoming_text="",
        tool_set=_tool_set(),
    )
    assert out is not None
    plan = Plan.model_validate(out)
    assert plan.steps[0].title == "do the thing"
