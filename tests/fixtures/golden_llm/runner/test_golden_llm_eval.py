"""W12 span evaluators, pydantic-evals dataset gate, and native parity tests."""

from __future__ import annotations

import pytest
from pydantic_evals.evaluators import HasMatchingSpan
from pydantic_evals.evaluators.context import EvaluatorContext

from sevn.self_improve.eval.replay import (
    DEFAULT_INTENT_MATCH_THRESHOLD,
    DEFAULT_TOOLS_MATCH_THRESHOLD,
    golden_routing_fixture_path,
    run_golden_routing_replay,
)
from tests.fixtures.golden_llm.dataset import build_golden_eval_dataset, ci_golden_case_ids
from tests.fixtures.golden_llm.eval_runner import (
    assert_report_passed,
    configure_golden_eval_otel,
    run_golden_eval_report,
    run_golden_eval_report_async,
)
from tests.fixtures.golden_llm.evaluators import (
    GoldenRunOutput,
    ResponseContainsEvaluator,
    build_case_evaluators,
    tool_span_query,
)
from tests.fixtures.golden_llm.harness import (
    discover_cases,
    load_recording,
)
from tests.fixtures.golden_llm.parity import (
    ParityCaseResult,
    ParityReport,
    ParitySnapshot,
    compare_snapshots,
    run_parity_report,
    save_native_snapshot,
    slot_flip_blocked,
)

_REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[4]


def test_build_golden_eval_dataset_has_span_evaluators() -> None:
    """Dataset rows carry span-based tool evaluators (W12.1)."""
    dataset = build_golden_eval_dataset(case_ids=("read_01",))
    assert len(dataset.cases) == 1
    evaluator_names = {type(ev).__name__ for ev in dataset.cases[0].evaluators}
    assert "HasMatchingSpan" in evaluator_names
    assert dataset.report_evaluators


@pytest.mark.asyncio
async def test_golden_eval_dataset_runs_offline_via_replay() -> None:
    """CI golden subset runs tokenlessly through pydantic-evals (W12.5)."""
    report = await run_golden_eval_report_async(case_ids=ci_golden_case_ids())
    assert_report_passed(report)


def test_golden_eval_ci_subset_passes_sync() -> None:
    """Synchronous eval gate for Makefile ``golden-llm-ci``."""
    report = run_golden_eval_report(case_ids=ci_golden_case_ids())
    assert_report_passed(report)


def test_span_evaluator_flags_missing_tool_call() -> None:
    """HasMatchingSpan fails when the tool span is absent (W12.5)."""
    configure_golden_eval_otel()
    evaluator = HasMatchingSpan(query=tool_span_query("read"), evaluation_name="span_tool_read")
    ctx = EvaluatorContext(
        name="missing-tool",
        inputs="read_01",
        metadata=None,
        expected_output=None,
        output=GoldenRunOutput(
            case_id="missing-tool",
            status="completed",
            tool_names=(),
            final_text="",
            provider_messages=(),
        ),
        duration=0.01,
        _span_tree=__import__("pydantic_evals.otel.span_tree", fromlist=["SpanTree"]).SpanTree(),
        attributes={},
        metrics={},
    )
    assert evaluator.evaluate(ctx) is False


def test_response_contains_evaluator_checks_final_text() -> None:
    """Output evaluator reads ``GoldenRunOutput.final_text``."""
    evaluator = ResponseContainsEvaluator(fragment="hello")
    ctx = EvaluatorContext(
        name="x",
        inputs="x",
        metadata=None,
        expected_output=None,
        output=GoldenRunOutput(
            case_id="x",
            status="completed",
            tool_names=("read",),
            final_text="hello world",
            provider_messages=(),
        ),
        duration=0.0,
        _span_tree=__import__("pydantic_evals.otel.span_tree", fromlist=["SpanTree"]).SpanTree(),
        attributes={},
        metrics={},
    )
    assert evaluator.evaluate(ctx) is True


@pytest.mark.asyncio
async def test_parity_report_matches_recordings_tokenless() -> None:
    """FunctionModel replay matches W11 recording baselines (W12.2)."""
    report = await run_parity_report(case_ids=("read_01", "glob_01"))
    assert report.total >= 2
    assert report.match_rate == 1.0
    assert slot_flip_blocked(report) is False


def test_native_parity_blocks_flip_on_divergence() -> None:
    """Parity gate blocks default-native flip when native snapshot diverges (W12.5)."""
    from tests.fixtures.golden_llm.parity import NATIVE_SNAPSHOTS_ROOT, load_native_snapshot

    case_id = "parity-test-case"
    baseline = ParitySnapshot(tool_names=("read",), final_text="hello world")
    divergent = ParitySnapshot(tool_names=("write",), final_text="different")
    sidecar = save_native_snapshot(case_id, divergent)
    try:
        loaded = load_native_snapshot(case_id)
        assert loaded is not None
        ok, _ = compare_snapshots(baseline=baseline, candidate=loaded)
        assert ok is False
        report = ParityReport(
            case_results=(
                ParityCaseResult(
                    case_id=case_id,
                    matched=False,
                    function_model=baseline,
                    native=divergent,
                    detail="native diverged",
                ),
            ),
            matched_count=0,
            total=1,
        )
        assert slot_flip_blocked(report) is True
    finally:
        sidecar.unlink(missing_ok=True)
        if NATIVE_SNAPSHOTS_ROOT.is_dir() and not any(NATIVE_SNAPSHOTS_ROOT.iterdir()):
            NATIVE_SNAPSHOTS_ROOT.rmdir()


def test_golden_routing_tools_match_rate_with_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Triager golden_routing gate includes tool-list accuracy (W12.3)."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    result = run_golden_routing_replay(
        repo_root=_REPO_ROOT,
        sample_size=20,
        intent_threshold=DEFAULT_INTENT_MATCH_THRESHOLD,
        tools_threshold=DEFAULT_TOOLS_MATCH_THRESHOLD,
    )
    assert result.segment.status == "passed"
    assert result.metrics.tools_match_rate >= DEFAULT_TOOLS_MATCH_THRESHOLD
    assert golden_routing_fixture_path(repo_root=_REPO_ROOT).is_file()


def test_build_case_evaluators_from_golden_case() -> None:
    """Case evaluators derive from on-disk assertion fields."""
    cases = {c.id: c for c in discover_cases(category="tools")}
    evaluators = build_case_evaluators(cases["read_01"])
    assert len(evaluators) >= 3
    recording = load_recording(cases["read_01"])
    assert recording is not None
