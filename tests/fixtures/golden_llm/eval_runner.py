"""Tokenless pydantic-evals runner for golden_llm replay (W12).

Module: tests.fixtures.golden_llm.eval_runner
Depends: pydantic_evals, sevn.agent.tracing.otel_pipeline, tests.fixtures.golden_llm.dataset

Exports:
    configure_golden_eval_otel — in-memory TracerProvider for span evaluators.
    run_golden_eval_report — evaluate CI subset tokenlessly via record/replay.
    build_replay_task — async task factory for ``Dataset.evaluate``.
"""

from __future__ import annotations

import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from sevn.agent.tracing.otel_pipeline import reset_otel_pipeline_for_tests
from tests.fixtures.golden_llm.dataset import (
    GoldenCaseMetadata,
    build_golden_eval_dataset,
    ci_golden_case_ids,
)
from tests.fixtures.golden_llm.evaluators import GoldenRunOutput
from tests.fixtures.golden_llm.harness import (
    GoldenCase,
    authoritative_tool_names_for_outcome,
    discover_cases,
    load_recording,
    prepare_workspace,
    run_golden_case_replay,
)

if TYPE_CHECKING:
    from pydantic_evals.reporting import EvaluationReport


def configure_golden_eval_otel() -> None:
    """Install a fresh in-process ``TracerProvider`` for span-based evaluators.

    Examples:
        >>> configure_golden_eval_otel() is None
        True
    """
    reset_otel_pipeline_for_tests()


def _cases_by_id() -> dict[str, GoldenCase]:
    return {case.id: case for case in discover_cases()}


def build_replay_task(
    *,
    cases: dict[str, GoldenCase] | None = None,
) -> Callable[[str], Awaitable[GoldenRunOutput]]:
    """Build a dataset task that replays one golden case tokenlessly.

    Args:
        cases (dict[str, GoldenCase] | None): Preloaded case map; defaults to full corpus.

    Returns:
        Callable: Async task accepting a case id string.

    Examples:
        >>> callable(build_replay_task())
        True
    """
    case_map = cases or _cases_by_id()

    async def _task(case_id: str) -> GoldenRunOutput:
        case = case_map[case_id]
        recording = load_recording(case)
        if recording is None:
            msg = f"missing recording for case {case_id}"
            raise AssertionError(msg)
        with tempfile.TemporaryDirectory(prefix="golden-eval-") as tmp:
            root = prepare_workspace(Path(tmp), case)
            outcome = await run_golden_case_replay(
                case,
                root,
                recording,
                turn_id=f"eval-{case_id}",
            )
        provider_msgs = tuple(dict(m) for m in outcome.provider_turn_messages)
        tool_names = tuple(
            authoritative_tool_names_for_outcome(
                list(provider_msgs),
                successful_tools_called=getattr(outcome, "successful_tools_called", None),
            ),
        )
        final_text = " ".join(m.text for m in outcome.final_messages)
        return GoldenRunOutput(
            case_id=case_id,
            status=str(outcome.status),
            tool_names=tool_names,
            final_text=final_text,
            provider_messages=provider_msgs,
        )

    return _task


def run_golden_eval_report(
    *,
    case_ids: tuple[str, ...] | None = None,
    max_concurrency: int = 4,
) -> EvaluationReport[str, GoldenRunOutput, GoldenCaseMetadata]:
    """Run the golden eval dataset tokenlessly and return the pydantic-evals report.

    Args:
        case_ids (tuple[str, ...] | None): Case subset; defaults to :func:`ci_golden_case_ids`.
        max_concurrency (int): Parallel replay limit.

    Returns:
        EvaluationReport: Full evaluation report with span + output assertions.

    Examples:
        >>> report = run_golden_eval_report(case_ids=("read_01",))
        >>> report.cases[0].name
        'read_01'
    """
    configure_golden_eval_otel()
    subset = case_ids if case_ids is not None else ci_golden_case_ids()
    dataset = build_golden_eval_dataset(case_ids=subset)
    task = build_replay_task()
    return dataset.evaluate_sync(
        task,
        name="golden_llm_replay",
        max_concurrency=max_concurrency,
        progress=False,
    )


async def run_golden_eval_report_async(
    *,
    case_ids: tuple[str, ...] | None = None,
    max_concurrency: int = 4,
) -> EvaluationReport[str, GoldenRunOutput, GoldenCaseMetadata]:
    """Async wrapper around dataset evaluation for pytest.

    Args:
        case_ids (tuple[str, ...] | None): Case subset; defaults to CI subset.
        max_concurrency (int): Parallel replay limit.

    Returns:
        EvaluationReport: Evaluation report from ``Dataset.evaluate``.

    Examples:
        >>> import asyncio
        >>> asyncio.run(run_golden_eval_report_async(case_ids=("read_01",))).cases[0].inputs
        'read_01'
    """
    configure_golden_eval_otel()
    subset = case_ids if case_ids is not None else ci_golden_case_ids()
    dataset = build_golden_eval_dataset(case_ids=subset)
    task = build_replay_task()
    return await dataset.evaluate(
        task,
        name="golden_llm_replay",
        max_concurrency=max_concurrency,
        progress=False,
    )


def assert_report_passed(
    report: EvaluationReport[str, GoldenRunOutput, GoldenCaseMetadata],
) -> None:
    """Raise ``AssertionError`` when any case assertion failed or task errored.

    Args:
        report (EvaluationReport): Report from :func:`run_golden_eval_report`.

    Examples:
        >>> assert_report_passed.__name__
        'assert_report_passed'
    """
    if report.failures:
        first = report.failures[0]
        msg = f"golden eval task failure: {first.name}: {first.error_message}"
        raise AssertionError(msg)
    for case in report.cases:
        failed = [name for name, result in case.assertions.items() if not result.value]
        if failed:
            msg = f"case {case.name}: failed assertions {failed}"
            raise AssertionError(msg)


__all__ = [
    "assert_report_passed",
    "build_replay_task",
    "configure_golden_eval_otel",
    "run_golden_eval_report",
    "run_golden_eval_report_async",
]
