"""Span-based and output evaluators for golden_llm pydantic-evals (W12).

Module: tests.fixtures.golden_llm.evaluators
Depends: pydantic_evals, tests.fixtures.golden_llm.harness

Exports:
    GoldenRunOutput — task output bundle for dataset evaluation.
    build_case_evaluators — per-case evaluator list from ``GoldenCase`` assertions.
    build_dataset_report_evaluators — category pass-rate report evaluators.
    conversation_eval_rubric_path — path to optional LLM-judge rubric.
    optional_llm_judge_evaluator — opt-in ``LLMJudge`` (live keys only).
    tool_span_query — ``SpanQuery`` for one executed tool name.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic_evals.evaluators import Evaluator, EvaluatorContext, HasMatchingSpan
from pydantic_evals.evaluators.report_evaluator import ReportEvaluator, ReportEvaluatorContext
from pydantic_evals.reporting.analyses import ReportAnalysis, ScalarResult

if TYPE_CHECKING:
    from tests.fixtures.golden_llm.harness import GoldenCase, GoldenRecording

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RUBRIC_PATH = _REPO_ROOT / "tools" / "conversation_eval_rubric.md"


@dataclass(frozen=True, slots=True)
class GoldenRunOutput:
    """Structured tier-B replay output for pydantic-evals tasks."""

    case_id: str
    status: str
    tool_names: tuple[str, ...]
    final_text: str
    provider_messages: tuple[dict[str, Any], ...]


def conversation_eval_rubric_path() -> Path:
    """Return the optional LLM-judge rubric file used by ``conversation_eval.py``.

    Returns:
        Path: Repo-relative rubric markdown path.

    Examples:
        >>> conversation_eval_rubric_path().name
        'conversation_eval_rubric.md'
    """
    return _RUBRIC_PATH


def tool_span_query(tool_name: str) -> dict[str, Any]:
    """Build a span query matching pydantic-ai ``execute_tool`` spans.

    Args:
        tool_name (str): Registry tool name (``gen_ai.tool.name`` attribute).

    Returns:
        SpanQuery: Query for :class:`HasMatchingSpan`.

    Examples:
        >>> tool_span_query("read")["has_attributes"]["gen_ai.tool.name"]
        'read'
    """
    return {
        "has_attributes": {
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": tool_name,
        },
    }


@dataclass(repr=False)
class ToolSuccessSpanEvaluator(Evaluator[str, GoldenRunOutput, dict[str, Any]]):
    """Assert no tool span ended in ERROR for the replayed turn."""

    evaluation_name: str = "tool_success"

    def evaluate(self, ctx: EvaluatorContext[str, GoldenRunOutput, dict[str, Any]]) -> bool:
        tree = ctx.span_tree
        if hasattr(tree, "any"):
            for node in tree:
                if node.attributes.get("gen_ai.operation.name") != "execute_tool":
                    continue
                status = node.attributes.get("otel.status_code") or node.attributes.get("status")
                if status in ("ERROR", "error"):
                    return False
        msgs = [dict(m) for m in ctx.output.provider_messages]
        if not msgs:
            return True
        errors = _tool_errors_from_messages(msgs)
        return not errors


@dataclass(repr=False)
class ToolsCalledOutputEvaluator(Evaluator[str, GoldenRunOutput, dict[str, Any]]):
    """Fallback tool-list check from ``provider_turn_messages`` when spans are absent."""

    expected_tools: tuple[str, ...]
    evaluation_name: str = "tools_called_output"

    def evaluate(self, ctx: EvaluatorContext[str, GoldenRunOutput, dict[str, Any]]) -> bool:
        names = list(ctx.output.tool_names)
        return all(tool in names for tool in self.expected_tools)


def _tool_errors_from_messages(messages: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    last_name = "?"
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use":
                last_name = str(part.get("name", "?"))
            elif part.get("type") == "tool_result":
                body = part.get("content")
                if isinstance(body, str) and '"ok":false' in body.replace(" ", ""):
                    errors.append(last_name)
    return errors


@dataclass(repr=False)
class ResponseContainsEvaluator(Evaluator[str, GoldenRunOutput, dict[str, Any]]):
    """Check assistant text contains an expected fragment."""

    fragment: str
    case_sensitive: bool = False
    evaluation_name: str | None = None

    def evaluate(self, ctx: EvaluatorContext[str, GoldenRunOutput, dict[str, Any]]) -> bool:
        text = ctx.output.final_text
        if not self.case_sensitive:
            text = text.lower()
            fragment = self.fragment.lower()
        else:
            fragment = self.fragment
        return fragment in text


def build_case_evaluators(
    case: GoldenCase,
) -> tuple[Evaluator[str, GoldenRunOutput, dict[str, Any]], ...]:
    """Build per-case evaluators from golden assertions (spans + output checks).

    Args:
        case (GoldenCase): Loaded golden case file.

    Returns:
        tuple[Evaluator, ...]: Evaluators attached to one ``pydantic_evals.Case``.

    Examples:
        >>> from tests.fixtures.golden_llm.harness import GoldenCase, GoldenRequires
        >>> c = GoldenCase(
        ...     id="x",
        ...     user_messages=["hi"],
        ...     triage_stub={"intent": "NEW_REQUEST", "complexity": "B", "first_message": "ok",
        ...                  "tools": ["read"], "skills": [], "mcp_servers_required": [],
        ...                  "confidence": 0.9, "requires_vision": False},
        ...     requires=GoldenRequires(tools=["read"]),
        ... )
        >>> len(build_case_evaluators(c)) >= 2
        True
    """
    evaluators: list[Evaluator[str, GoldenRunOutput, dict[str, Any]]] = []
    for tool in case.assertions.tools_called:
        evaluators.append(
            HasMatchingSpan(
                query=tool_span_query(tool),
                evaluation_name=f"span_tool_{tool}",
            ),
        )
    if case.assertions.tools_called:
        evaluators.append(
            ToolsCalledOutputEvaluator(expected_tools=tuple(case.assertions.tools_called)),
        )
    if case.assertions.tool_success:
        evaluators.append(ToolSuccessSpanEvaluator())
    for idx, fragment in enumerate(case.assertions.response_contains):
        evaluators.append(
            ResponseContainsEvaluator(
                fragment=fragment,
                evaluation_name=f"response_contains_{idx}",
            ),
        )
    return tuple(evaluators)


@dataclass(repr=False)
class CategoryPassRateReportEvaluator(
    ReportEvaluator[str, GoldenRunOutput, dict[str, Any]],
):
    """Report evaluator: mean assertion pass rate grouped by golden case category."""

    evaluation_name: str = "category_pass_rate"

    def evaluate(
        self,
        ctx: ReportEvaluatorContext[str, GoldenRunOutput, dict[str, Any]],
    ) -> list[ReportAnalysis]:
        buckets: dict[str, list[float]] = defaultdict(list)
        for report_case in ctx.report.cases:
            category = "unknown"
            if isinstance(report_case.metadata, dict):
                category = str(report_case.metadata.get("category") or "unknown")
            if not report_case.assertions:
                buckets[category].append(1.0)
                continue
            passed = sum(1 for assertion in report_case.assertions.values() if assertion.value)
            total = len(report_case.assertions)
            buckets[category].append(passed / total if total else 1.0)
        analyses: list[ReportAnalysis] = []
        for category, rates in sorted(buckets.items()):
            mean_rate = sum(rates) / len(rates) if rates else 0.0
            analyses.append(
                ScalarResult(
                    name=f"{self.evaluation_name}.{category}",
                    value=mean_rate,
                    unit="ratio",
                    description=f"Mean assertion pass rate for category {category!r}",
                ),
            )
        return analyses


def build_dataset_report_evaluators() -> tuple[
    ReportEvaluator[str, GoldenRunOutput, dict[str, Any]], ...
]:
    """Return dataset-level report evaluators for golden_llm runs.

    Returns:
        tuple[ReportEvaluator, ...]: Category aggregate evaluators.

    Examples:
        >>> len(build_dataset_report_evaluators())
        1
    """
    return (CategoryPassRateReportEvaluator(),)


def optional_llm_judge_evaluator() -> Evaluator[str, GoldenRunOutput, dict[str, Any]] | None:
    """Return an ``LLMJudge`` when live keys are enabled; otherwise ``None``.

    Returns:
        LLMJudge | None: Opt-in quality judge (never used in tokenless CI).

    Examples:
        >>> optional_llm_judge_evaluator() is None
        True
    """
    from tests.fixtures.golden_llm.harness import golden_llm_live_enabled

    if not golden_llm_live_enabled():
        return None
    if not _RUBRIC_PATH.is_file():
        return None
    from pydantic_evals.evaluators import LLMJudge

    rubric = _RUBRIC_PATH.read_text(encoding="utf-8")
    return LLMJudge(
        rubric=rubric,
        include_input=True,
        assertion={"evaluation_name": "conversation_quality", "include_reason": True},
    )


def snapshot_from_output(output: GoldenRunOutput) -> dict[str, Any]:
    """Serialize a :class:`GoldenRunOutput` for parity comparisons.

    Args:
        output (GoldenRunOutput): Replay task output.

    Returns:
        dict[str, Any]: JSON-serializable tool/text snapshot.

    Examples:
        >>> snapshot_from_output(GoldenRunOutput(
        ...     case_id="x", status="completed", tool_names=("read",),
        ...     final_text="ok", provider_messages=(),
        ... ))["tool_names"]
        ['read']
    """
    return {
        "tool_names": list(output.tool_names),
        "final_text": output.final_text,
    }


def snapshot_from_recording(*, recording: GoldenRecording) -> dict[str, Any]:
    """Build a parity baseline from a recorded turn.

    Args:
        recording (GoldenRecording): W11 recording payload.

    Returns:
        dict[str, Any]: Baseline snapshot for parity checks.

    Examples:
        >>> from tests.fixtures.golden_llm.harness import GoldenRecording
        >>> snapshot_from_recording(recording=GoldenRecording(
        ...     case_id="x", transport_responses=[], final_text="hi",
        ... ))["final_text"]
        'hi'
    """
    from tests.fixtures.golden_llm.harness import (
        tool_names_from_provider_messages,
        tool_names_from_transport_responses,
    )

    tool_messages = list(recording.provider_turn_messages)
    if tool_messages:
        tool_names = tool_names_from_provider_messages(tool_messages)
    else:
        tool_names = tool_names_from_transport_responses(recording.transport_responses)
    return {
        "tool_names": tool_names,
        "final_text": recording.final_text,
    }


__all__ = [
    "CategoryPassRateReportEvaluator",
    "GoldenRunOutput",
    "ResponseContainsEvaluator",
    "ToolSuccessSpanEvaluator",
    "ToolsCalledOutputEvaluator",
    "build_case_evaluators",
    "build_dataset_report_evaluators",
    "conversation_eval_rubric_path",
    "optional_llm_judge_evaluator",
    "snapshot_from_output",
    "snapshot_from_recording",
    "tool_span_query",
]
