"""Tokenless replay comparison report for Hermes eval (#91, W32).

Module: sevn.model_eval.replay
Depends: pydantic_evals, sevn.model_eval.suite, tests.fixtures.golden_llm.eval_runner

Exports:
    CaseReplayResult — one case outcome row.
    ReplayComparisonReport — JSON-serializable tokenless report.
    run_replay_comparison_report — evaluate suite via golden_llm replay harness.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sevn.golden_llm.eval_runner import run_golden_eval_report
from sevn.golden_llm.harness import load_recording
from sevn.model_eval.config import D21_DECISION
from sevn.model_eval.suite import hermes_eval_suite_case_ids, scenario_for_case


@dataclass(frozen=True, slots=True)
class CaseReplayResult:
    """One case outcome in a tokenless replay report."""

    case_id: str
    scenario: str | None
    passed: bool
    assertion_pass_rate: float
    failed_assertions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplayComparisonReport:
    """Advisory tokenless comparison report (single baseline replay)."""

    mode: str
    d21_decision: str
    case_ids: tuple[str, ...]
    cases: tuple[CaseReplayResult, ...]
    scenario_pass_rates: dict[str, float] = field(default_factory=dict)
    overall_pass_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize for skill script stdout.

        Returns:
            dict[str, Any]: JSON-serializable report payload.

        Examples:
            >>> ReplayComparisonReport(
            ...     mode="replay", d21_decision="x", case_ids=(), cases=(),
            ... ).to_dict()["mode"]
            'replay'
        """
        return {
            "mode": self.mode,
            "d21_decision": self.d21_decision,
            "case_ids": list(self.case_ids),
            "overall_pass_rate": self.overall_pass_rate,
            "scenario_pass_rates": dict(self.scenario_pass_rates),
            "cases": [
                {
                    "case_id": row.case_id,
                    "scenario": row.scenario,
                    "passed": row.passed,
                    "assertion_pass_rate": row.assertion_pass_rate,
                    "failed_assertions": list(row.failed_assertions),
                }
                for row in self.cases
            ],
        }


def run_replay_comparison_report(
    *,
    case_ids: tuple[str, ...] | None = None,
) -> ReplayComparisonReport:
    """Run the Hermes eval suite tokenlessly via golden_llm replay.

    Args:
        case_ids (tuple[str, ...] | None): Override suite; defaults to :func:`hermes_eval_suite_case_ids`.

    Returns:
        ReplayComparisonReport: Advisory pass-rate report (no routing changes).

    Examples:
        >>> report = run_replay_comparison_report(case_ids=("read_01",))
        >>> report.mode == "replay"
        True
    """
    subset = case_ids if case_ids is not None else hermes_eval_suite_case_ids()
    for case_id in subset:
        from tests.fixtures.golden_llm.harness import discover_cases

        case_map = {c.id: c for c in discover_cases()}
        case = case_map.get(case_id)
        if case is None:
            msg = f"unknown golden case {case_id!r}"
            raise ValueError(msg)
        if load_recording(case) is None:
            msg = f"missing recording for case {case_id!r}"
            raise ValueError(msg)

    eval_report = run_golden_eval_report(case_ids=subset)
    case_rows: list[CaseReplayResult] = []
    scenario_rates: dict[str, list[float]] = defaultdict(list)

    for report_case in eval_report.cases:
        assertions = report_case.assertions or {}
        if assertions:
            passed_count = sum(1 for item in assertions.values() if item.value)
            rate = passed_count / len(assertions)
            failed = tuple(name for name, item in assertions.items() if not item.value)
        else:
            rate = 1.0
            failed = ()
        scenario = scenario_for_case(report_case.name)
        row = CaseReplayResult(
            case_id=report_case.name,
            scenario=scenario,
            passed=rate >= 1.0 and not report_case.evaluator_failures,
            assertion_pass_rate=rate,
            failed_assertions=failed,
        )
        case_rows.append(row)
        if scenario:
            scenario_rates[scenario].append(rate)

    aggregated = {
        name: (sum(rates) / len(rates) if rates else 0.0)
        for name, rates in sorted(scenario_rates.items())
    }
    overall = sum(r.assertion_pass_rate for r in case_rows) / len(case_rows) if case_rows else 0.0

    return ReplayComparisonReport(
        mode="replay",
        d21_decision=D21_DECISION,
        case_ids=subset,
        cases=tuple(case_rows),
        scenario_pass_rates=aggregated,
        overall_pass_rate=overall,
    )


__all__ = [
    "CaseReplayResult",
    "ReplayComparisonReport",
    "run_replay_comparison_report",
]
