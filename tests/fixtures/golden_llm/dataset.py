"""Build ``pydantic_evals.Dataset`` instances from golden_llm cases (W12).

Module: tests.fixtures.golden_llm.dataset
Depends: pydantic_evals, tests.fixtures.golden_llm.evaluators, tests.fixtures.golden_llm.harness

Exports:
    GoldenCaseMetadata — typed metadata payload on each dataset row.
    build_golden_eval_dataset — full dataset with span + output evaluators.
    ci_golden_case_ids — tokenless CI subset (one per category minimum).
"""

from __future__ import annotations

from typing import Any, TypedDict

from pydantic_evals import Case, Dataset

from tests.fixtures.golden_llm.evaluators import (
    GoldenRunOutput,
    build_case_evaluators,
    build_dataset_report_evaluators,
    optional_llm_judge_evaluator,
)
from tests.fixtures.golden_llm.harness import discover_cases, load_recording


class GoldenCaseMetadata(TypedDict):
    """Metadata attached to each golden eval case row."""

    case: dict[str, Any]
    category: str
    has_recording: bool


def ci_golden_case_ids() -> tuple[str, ...]:
    """Return a stable tokenless CI subset spanning tools/skills/input/codemode.

    Returns:
        tuple[str, ...]: Case ids replayed in the CI golden gate.

    Examples:
        >>> ids = ci_golden_case_ids()
        >>> "read_01" in ids
        True
    """
    return (
        "read_01",
        "glob_01",
        "vision_01",
        "composite_glob_read_01",
    )


def build_golden_eval_dataset(
    *,
    category: str | None = None,
    case_ids: tuple[str, ...] | None = None,
    include_llm_judge: bool = False,
) -> Dataset[str, GoldenRunOutput, GoldenCaseMetadata]:
    """Materialize a pydantic-evals dataset from on-disk golden cases.

    Args:
        category (str | None): Optional ``cases/<category>/`` filter.
        case_ids (tuple[str, ...] | None): When set, only these case ids are included.
        include_llm_judge (bool): Attach optional ``LLMJudge`` (live keys only).

    Returns:
        Dataset: Case inputs are stable case ids; evaluators include span checks.

    Examples:
        >>> ds = build_golden_eval_dataset(case_ids=("read_01",))
        >>> ds.cases[0].inputs
        'read_01'
    """
    cases = discover_cases(category=category)
    if case_ids is not None:
        wanted = set(case_ids)
        cases = [case for case in cases if case.id in wanted]
    rows: list[Case[str, GoldenRunOutput, GoldenCaseMetadata]] = []
    for case in cases:
        recording = load_recording(case)
        rows.append(
            Case(
                name=case.id,
                inputs=case.id,
                metadata={
                    "case": case.model_dump(),
                    "category": case.category,
                    "has_recording": recording is not None,
                },
                evaluators=build_case_evaluators(case),
            ),
        )
    dataset_evaluators: list[Any] = []
    judge = optional_llm_judge_evaluator() if include_llm_judge else None
    if judge is not None:
        dataset_evaluators.append(judge)
    return Dataset(
        name="golden_llm",
        cases=rows,
        evaluators=dataset_evaluators,
        report_evaluators=list(build_dataset_report_evaluators()),
    )


__all__ = [
    "GoldenCaseMetadata",
    "build_golden_eval_dataset",
    "ci_golden_case_ids",
]
