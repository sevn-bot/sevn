"""Fixed Hermes eval suite mapped to golden_llm cases (#91, W32).

Module: sevn.model_eval.suite
Depends: typing

Exports:
    hermes_eval_suite_case_ids — stable union for the advisory suite.
    scenario_classes — copy-safe scenario map accessor.
    scenario_for_case — reverse lookup from case id to scenario class.
"""

from __future__ import annotations

from typing import Final

SCENARIO_TOOL_CALL: Final[tuple[str, ...]] = ("read_01", "glob_01")
SCENARIO_CODING: Final[tuple[str, ...]] = ("edit_01", "composite_write_read_01")
SCENARIO_SUMMARIZATION: Final[tuple[str, ...]] = ("summarize_01",)
SCENARIO_POLICY_APPROVAL: Final[tuple[str, ...]] = ("policy_approval_01",)

SCENARIO_CLASSES: Final[dict[str, tuple[str, ...]]] = {
    "tool_call": SCENARIO_TOOL_CALL,
    "coding": SCENARIO_CODING,
    "summarization": SCENARIO_SUMMARIZATION,
    "policy_approval": SCENARIO_POLICY_APPROVAL,
}


def scenario_classes() -> dict[str, tuple[str, ...]]:
    """Return scenario-class → golden case ids (copy-safe).

    Returns:
        dict[str, tuple[str, ...]]: Scenario buckets for the fixed suite.

    Examples:
        >>> "tool_call" in scenario_classes()
        True
    """
    return dict(SCENARIO_CLASSES)


def hermes_eval_suite_case_ids() -> tuple[str, ...]:
    """Return the stable union of all Hermes eval suite case ids.

    Returns:
        tuple[str, ...]: Sorted unique case ids.

    Examples:
        >>> "read_01" in hermes_eval_suite_case_ids()
        True
    """
    seen: list[str] = []
    for case_ids in SCENARIO_CLASSES.values():
        for case_id in case_ids:
            if case_id not in seen:
                seen.append(case_id)
    return tuple(seen)


def scenario_for_case(case_id: str) -> str | None:
    """Map one case id back to its scenario class label.

    Args:
        case_id (str): Golden case id.

    Returns:
        str | None: Scenario class name when known.

    Examples:
        >>> scenario_for_case("read_01")
        'tool_call'
    """
    for name, case_ids in SCENARIO_CLASSES.items():
        if case_id in case_ids:
            return name
    return None


__all__ = [
    "hermes_eval_suite_case_ids",
    "scenario_classes",
    "scenario_for_case",
]
