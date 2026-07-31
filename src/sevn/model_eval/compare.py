"""Live multi-model comparison on golden_llm cases (#91, W32).

Module: sevn.model_eval.compare
Depends: asyncio, time, sevn.agent.providers, sevn.model_eval.config, sevn.model_eval.suite

Exports:
    LiveCaseResult — one model x case live outcome.
    LiveComparisonReport — cross-model advisory comparison report.
    run_live_model_comparison — run suite live across configured models.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sevn.agent.providers.resolve import resolve_model
from sevn.config.model_resolution import resolve_transport_for_model_id
from sevn.config.sections.providers import providers_section_dict
from sevn.model_eval.config import (
    D21_DECISION,
    HERMES_EVAL_LIVE_ENV,
    HermesEvalModelSpec,
    hermes_eval_live_enabled,
    resolve_hermes_eval_models,
)
from sevn.model_eval.suite import hermes_eval_suite_case_ids, scenario_for_case


def _golden_eval_imports() -> tuple[Any, Any, Any, Any, Any, Any]:
    """Import golden_llm test fixtures lazily (dev/test paths only).

    Returns:
        tuple[Any, ...]: Evaluator helpers and harness callables.

    Examples:
        >>> len(_golden_eval_imports())
        6
    """
    from tests.fixtures.golden_llm.evaluators import GoldenRunOutput, build_case_evaluators
    from tests.fixtures.golden_llm.harness import (
        authoritative_tool_names_for_outcome,
        discover_cases,
        prepare_workspace,
        run_golden_case_live,
    )

    return (
        GoldenRunOutput,
        build_case_evaluators,
        authoritative_tool_names_for_outcome,
        discover_cases,
        prepare_workspace,
        run_golden_case_live,
    )


if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig


@dataclass(frozen=True, slots=True)
class LiveCaseResult:
    """One live eval row (model x case)."""

    model_label: str
    model_id: str
    case_id: str
    scenario: str | None
    passed: bool
    assertion_pass_rate: float
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    status: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class LiveComparisonReport:
    """Advisory live cross-model comparison (does not mutate routing)."""

    mode: str
    d21_decision: str
    models: tuple[dict[str, str], ...]
    case_ids: tuple[str, ...]
    results: tuple[LiveCaseResult, ...]
    model_pass_rates: dict[str, float] = field(default_factory=dict)
    scenario_pass_rates: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for skill script stdout.

        Returns:
            dict[str, Any]: JSON-serializable report payload.

        Examples:
            >>> LiveComparisonReport(
            ...     mode="live", d21_decision="x", models=(), case_ids=(), results=(),
            ... ).to_dict()["mode"]
            'live'
        """
        return {
            "mode": self.mode,
            "d21_decision": self.d21_decision,
            "models": list(self.models),
            "case_ids": list(self.case_ids),
            "model_pass_rates": dict(self.model_pass_rates),
            "scenario_pass_rates": {
                model: dict(rates) for model, rates in self.scenario_pass_rates.items()
            },
            "results": [
                {
                    "model_label": row.model_label,
                    "model_id": row.model_id,
                    "case_id": row.case_id,
                    "scenario": row.scenario,
                    "passed": row.passed,
                    "assertion_pass_rate": row.assertion_pass_rate,
                    "latency_ms": row.latency_ms,
                    "prompt_tokens": row.prompt_tokens,
                    "completion_tokens": row.completion_tokens,
                    "status": row.status,
                    "error": row.error,
                }
                for row in self.results
            ],
        }


def _proxy_headers() -> dict[str, str]:
    """Build optional proxy auth headers from process env.

    Returns:
        dict[str, str]: Header map (may be empty).

    Examples:
        >>> isinstance(_proxy_headers(), dict)
        True
    """
    headers: dict[str, str] = {}
    secret = os.environ.get("SEVN_PROXY_SHARED_SECRET", "").strip()
    if secret:
        headers["X-Sevn-Proxy-Token"] = secret
    session_token = os.environ.get("SEVN_SESSION_TOKEN", "").strip()
    if session_token:
        headers["X-Sevn-Session-Token"] = session_token
    return headers


def _resolve_proxy_url(workspace: WorkspaceConfig) -> str:
    """Resolve egress proxy base URL for live eval transports.

    Args:
        workspace (WorkspaceConfig): Bound workspace config.

    Returns:
        str: Proxy origin URL (may be empty when unset).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> isinstance(_resolve_proxy_url(WorkspaceConfig.minimal()), str)
        True
    """
    proxy_url = os.environ.get("SEVN_PROXY_URL", "").strip()
    if proxy_url:
        return proxy_url
    from sevn.cli.gateway_client import resolve_proxy_base_url

    return resolve_proxy_base_url(workspace=workspace).strip()


def _usage_from_responses(responses: list[dict[str, Any]]) -> tuple[int, int]:
    """Sum prompt/completion token usage from transport response payloads.

    Args:
        responses (list[dict[str, Any]]): Recorded transport responses.

    Returns:
        tuple[int, int]: ``(prompt_tokens, completion_tokens)``.

    Examples:
        >>> _usage_from_responses([{"usage": {"prompt_tokens": 1, "completion_tokens": 2}}])
        (1, 2)
    """
    prompt = completion = 0
    for response in responses:
        usage = response.get("usage")
        if not isinstance(usage, dict):
            continue
        prompt += int(usage.get("prompt_tokens") or 0)
        completion += int(usage.get("completion_tokens") or 0)
    return prompt, completion


async def _run_one_live(
    *,
    case: Any,
    spec: HermesEvalModelSpec,
    workspace: WorkspaceConfig,
    proxy_url: str,
) -> LiveCaseResult:
    """Execute one golden case against a live model transport.

    Args:
        case (GoldenCase): Loaded golden case payload.
        spec (HermesEvalModelSpec): Model alias under test.
        workspace (WorkspaceConfig): Bound workspace config.
        proxy_url (str): Egress proxy base URL.

    Returns:
        LiveCaseResult: Pass rate, latency, and token usage for the row.

    Examples:
        >>> _run_one_live.__name__
        '_run_one_live'
    """
    (
        GoldenRunOutput,
        build_case_evaluators,
        authoritative_tool_names_for_outcome,
        _discover_cases,
        prepare_workspace,
        run_golden_case_live,
    ) = _golden_eval_imports()
    providers = providers_section_dict(getattr(workspace, "providers", None))
    transport_name = resolve_transport_for_model_id(providers, spec.model_id)
    _mid, transport = resolve_model(
        model_id=spec.model_id,
        transport_name=transport_name,
        proxy_base_url=proxy_url,
        extra_headers=_proxy_headers(),
    )
    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="hermes-eval-") as tmp:
            root = prepare_workspace(Path(tmp), case)
            outcome, recording = await run_golden_case_live(
                case,
                root,
                transport,
                turn_id=f"hermes-{spec.label}-{case.id}",
            )
        latency_ms = (time.perf_counter() - started) * 1000.0
        provider_msgs = tuple(dict(m) for m in outcome.provider_turn_messages)
        tool_names = tuple(
            authoritative_tool_names_for_outcome(
                list(provider_msgs),
                successful_tools_called=getattr(outcome, "successful_tools_called", None),
            ),
        )
        final_text = " ".join(m.text for m in outcome.final_messages)
        run_output = GoldenRunOutput(
            case_id=case.id,
            status=str(outcome.status),
            tool_names=tool_names,
            final_text=final_text,
            provider_messages=provider_msgs,
        )
        evaluators = build_case_evaluators(case)
        passed_flags: list[bool] = []
        span_tree = __import__(
            "pydantic_evals.otel.span_tree",
            fromlist=["SpanTree"],
        ).SpanTree()
        evaluator_ctx = __import__(
            "pydantic_evals.evaluators.context",
            fromlist=["EvaluatorContext"],
        ).EvaluatorContext
        for evaluator in evaluators:
            ctx = evaluator_ctx(
                name=case.id,
                inputs=case.id,
                metadata={"case": case.model_dump(), "category": case.category},
                expected_output=None,
                output=run_output,
                duration=latency_ms / 1000.0,
                _span_tree=span_tree,
                attributes={},
                metrics={},
            )
            passed_flags.append(bool(evaluator.evaluate(ctx)))
        rate = sum(1 for flag in passed_flags if flag) / len(passed_flags) if passed_flags else 1.0
        prompt_tokens, completion_tokens = _usage_from_responses(recording.transport_responses)
        return LiveCaseResult(
            model_label=spec.label,
            model_id=spec.model_id,
            case_id=case.id,
            scenario=scenario_for_case(case.id),
            passed=rate >= 1.0 and str(outcome.status) == "completed",
            assertion_pass_rate=rate,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            status=str(outcome.status),
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        return LiveCaseResult(
            model_label=spec.label,
            model_id=spec.model_id,
            case_id=case.id,
            scenario=scenario_for_case(case.id),
            passed=False,
            assertion_pass_rate=0.0,
            latency_ms=latency_ms,
            prompt_tokens=0,
            completion_tokens=0,
            status="error",
            error=str(exc),
        )


async def _run_live_async(
    *,
    workspace: WorkspaceConfig,
    models: tuple[HermesEvalModelSpec, ...],
    case_ids: tuple[str, ...],
) -> LiveComparisonReport:
    """Run all model x case combinations and aggregate pass rates.

    Args:
        workspace (WorkspaceConfig): Bound workspace config.
        models (tuple[HermesEvalModelSpec, ...]): Model aliases to compare.
        case_ids (tuple[str, ...]): Golden case ids to execute.

    Returns:
        LiveComparisonReport: Cross-model advisory comparison payload.

    Examples:
        >>> _run_live_async.__name__
        '_run_live_async'
    """
    (
        _GoldenRunOutput,
        _build_case_evaluators,
        _authoritative_tool_names_for_outcome,
        discover_cases,
        _prepare_workspace,
        _run_golden_case_live,
    ) = _golden_eval_imports()
    case_map = {c.id: c for c in discover_cases()}
    proxy_url = _resolve_proxy_url(workspace)
    if not proxy_url:
        msg = "SEVN_PROXY_URL is not configured for live Hermes model eval"
        raise RuntimeError(msg)

    results: list[LiveCaseResult] = []
    for spec in models:
        for case_id in case_ids:
            case = case_map.get(case_id)
            if case is None:
                msg = f"unknown golden case {case_id!r}"
                raise ValueError(msg)
            results.append(
                await _run_one_live(case=case, spec=spec, workspace=workspace, proxy_url=proxy_url),
            )

    model_rates: dict[str, list[float]] = defaultdict(list)
    scenario_by_model: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in results:
        model_rates[row.model_label].append(row.assertion_pass_rate)
        if row.scenario:
            scenario_by_model[row.model_label][row.scenario].append(row.assertion_pass_rate)

    return LiveComparisonReport(
        mode="live",
        d21_decision=D21_DECISION,
        models=tuple({"label": s.label, "model_id": s.model_id} for s in models),
        case_ids=case_ids,
        results=tuple(results),
        model_pass_rates={
            label: (sum(rates) / len(rates) if rates else 0.0)
            for label, rates in sorted(model_rates.items())
        },
        scenario_pass_rates={
            label: {
                scenario: (sum(rates) / len(rates) if rates else 0.0)
                for scenario, rates in sorted(scenarios.items())
            }
            for label, scenarios in sorted(scenario_by_model.items())
        },
    )


def run_live_model_comparison(
    workspace: WorkspaceConfig,
    *,
    case_ids: tuple[str, ...] | None = None,
    models: tuple[HermesEvalModelSpec, ...] | None = None,
) -> LiveComparisonReport:
    """Run the Hermes eval suite live across configured model aliases.

    Requires ``SEVN_HERMES_MODEL_EVAL=1``, a reachable egress proxy, and provider
    keys. Results are advisory — they do not change routing defaults (D9).

    Args:
        workspace (WorkspaceConfig): Bound workspace config.
        case_ids (tuple[str, ...] | None): Override suite case ids.
        models (tuple[HermesEvalModelSpec, ...] | None): Override model matrix.

    Returns:
        LiveComparisonReport: Cross-model comparison with latency and token usage.

    Raises:
        RuntimeError: When live gate or proxy is unavailable.

    Examples:
        >>> run_live_model_comparison.__name__
        'run_live_model_comparison'
    """
    if not hermes_eval_live_enabled():
        msg = f"{HERMES_EVAL_LIVE_ENV}=1 required for live Hermes model eval"
        raise RuntimeError(msg)
    subset = case_ids if case_ids is not None else hermes_eval_suite_case_ids()
    model_specs = models if models is not None else resolve_hermes_eval_models(workspace)
    return asyncio.run(
        _run_live_async(workspace=workspace, models=model_specs, case_ids=subset),
    )


__all__ = [
    "LiveCaseResult",
    "LiveComparisonReport",
    "run_live_model_comparison",
]
