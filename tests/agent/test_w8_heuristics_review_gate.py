"""W8 review gate — registry drift pins, failure-marker pins, CodeMode evidence plumbing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sevn.agent.adapters.tier_b_codemode import (
    CODEMODE_NATIVE_TOOL_NAMES,
    CODEMODE_SKILL_RUNNER_NAMES,
)
from sevn.agent.executors import b_harness
from sevn.agent.grounding import (
    EVIDENCE_TOOLS,
    FILE_DELIVERY_TOOL_NAMES,
    GROUNDING_TOOL_NAMES,
    apply_audit_evidence_guard,
)
from sevn.gateway.agent_turn import (
    _DETERMINISTIC_HARNESS_FAILURE_MARKERS,
    _is_deterministic_harness_failure,
)
from sevn.prompts.fallbacks import CD_DECOMPOSE_PARSE_FAILURE_PREFIX
from sevn.tools.meta_loaders import META_TOOL_NAMES
from sevn.tools.registry import build_session_registry

# Hardcoded sets inventoried in W8.1 (plan/heuristics-consolidation-wave-plan.md).
_CODEMODE_TRACE_EXCLUDED: frozenset[str] = frozenset(
    {
        "run_code",
        "load_tool",
        "load_skill",
        "list_registry",
        "request_escalation",
    }
)
_TIER_B_ALWAYS_INVOKABLE: frozenset[str] = frozenset({"log_query", "list_registry"})
_TIER_B_ALWAYS_INVOKABLE_FILE_OPS: frozenset[str] = frozenset({"read", "edit", "write"})
_TIER_B_ALWAYS_INVOKABLE_SKILL_RUNNERS: frozenset[str] = frozenset(
    {"run_skill_script", "run_skill_runnable"},
)
_CAPABILITY_ONLY_TOOLS: frozenset[str] = frozenset({"run_code"})

_HEURISTIC_TOOL_SETS: dict[str, frozenset[str]] = {
    "GROUNDING_TOOL_NAMES": GROUNDING_TOOL_NAMES,
    "FILE_DELIVERY_TOOL_NAMES": FILE_DELIVERY_TOOL_NAMES,
    "EVIDENCE_TOOLS": EVIDENCE_TOOLS,
    "_EXECUTION_INTENT_TOOLS": b_harness._EXECUTION_INTENT_TOOLS,
    "META_TOOL_NAMES": META_TOOL_NAMES,
    "CODEMODE_NATIVE_TOOL_NAMES": CODEMODE_NATIVE_TOOL_NAMES,
    "CODEMODE_SKILL_RUNNER_NAMES": CODEMODE_SKILL_RUNNER_NAMES,
    "CODEMODE_TRACE_EXCLUDED": _CODEMODE_TRACE_EXCLUDED,
    "_ALWAYS_INVOKABLE_TIER_B": _TIER_B_ALWAYS_INVOKABLE,
    "_ALWAYS_INVOKABLE_FILE_OPS": _TIER_B_ALWAYS_INVOKABLE_FILE_OPS,
    "_ALWAYS_INVOKABLE_SKILL_RUNNERS": _TIER_B_ALWAYS_INVOKABLE_SKILL_RUNNERS,
}

# W8.2 — each marker must match at least one real production failure string.
_MARKER_PINNED_SOURCES: dict[str, str] = {
    "schema/parse failed": "cd.decompose schema/parse failed",
    "could not parse the execution plan": CD_DECOMPOSE_PARSE_FAILURE_PREFIX,
    "decompose schema": "cd.decompose schema/parse failed",
    "transportbadrequest": "TransportBadRequest",
    "llm_transport_bad_request": "llm_transport_bad_request path=/v1/messages",
    "invalid params": 'HTTP 400 "invalid params"',
    "returned 400": "LLM proxy returned 400 for /v1/messages",
    "complete_stream produced no final": "complete_stream produced no final payload",
    "upstream sse": "upstream SSE refused",
}

_FABRICATION_CONFESSION = (
    "I fabricated the audit answer — replay stub means I can't see any data and no tools ran."
)


@pytest.fixture(scope="module")
def registry_tool_names() -> frozenset[str]:
    """Enabled tool names from a default session registry (bootstrap tools included)."""
    exe, _ = build_session_registry(include_bootstrap_tools=True)
    return frozenset(d.name for d in exe.definitions())


@pytest.mark.parametrize("set_name", sorted(_HEURISTIC_TOOL_SETS))
def test_heuristic_tool_sets_exist_in_registry_or_are_meta(
    set_name: str,
    registry_tool_names: frozenset[str],
) -> None:
    """W8.1: every hardcoded heuristic tool name resolves to registry or known meta/capability."""
    names = _HEURISTIC_TOOL_SETS[set_name]
    allowed_without_registry = META_TOOL_NAMES | _CAPABILITY_ONLY_TOOLS
    missing = sorted(
        n for n in names if n not in registry_tool_names and n not in allowed_without_registry
    )
    assert not missing, f"{set_name} names missing from registry: {missing}"


def test_capability_key_not_wired_for_grounding_sets() -> None:
    """W8.1: ``ToolDefinition.capability_key`` exists but no tool sets it — flags not available."""
    exe, _ = build_session_registry(include_bootstrap_tools=True)
    with_capability = [d.name for d in exe.definitions() if d.capability_key]
    assert with_capability == []


@pytest.mark.parametrize(("marker", "source"), sorted(_MARKER_PINNED_SOURCES.items()))
def test_deterministic_harness_failure_markers_match_pinned_sources(
    marker: str,
    source: str,
) -> None:
    """W8.2: substring markers match at least one documented production failure string."""
    assert marker in _DETERMINISTIC_HARNESS_FAILURE_MARKERS
    assert marker in source.lower()
    outcome = SimpleNamespace(failure_detail=source)
    assert _is_deterministic_harness_failure(no_answer_reason=None, outcome=outcome)


def test_b_harness_failure_details_are_not_deterministic() -> None:
    """W8.2: tier-B filler/unavailable failures remain widened-retry eligible."""
    for detail in (
        "opener-only output (no substantive answer)",
        "triager_bound_tools_unused",
        "tool_unavailable_claim:serp",
        "promised_but_idle (motion-promise, no tool calls)",
    ):
        outcome = SimpleNamespace(failure_detail=detail)
        assert not _is_deterministic_harness_failure(no_answer_reason=None, outcome=outcome)


def test_audit_evidence_guard_fires_when_log_query_runs_inside_run_code() -> None:
    """W8.3: CodeMode lenient trace counts toward EVIDENCE_TOOLS."""
    out, applied = apply_audit_evidence_guard(
        _FABRICATION_CONFESSION,
        successful_tools=frozenset({"run_code"}),
        codemode_bound_tools_called=frozenset({"log_query"}),
    )
    assert applied
    assert out.startswith("**Correction:**")


def test_audit_evidence_guard_silent_without_codemode_trace() -> None:
    """W8.3: direct ``run_code`` alone does not satisfy evidence guard."""
    out, applied = apply_audit_evidence_guard(
        _FABRICATION_CONFESSION,
        successful_tools=frozenset({"run_code"}),
        codemode_bound_tools_called=frozenset(),
    )
    assert not applied
    assert out == _FABRICATION_CONFESSION
