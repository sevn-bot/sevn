"""Wave W4.3: tool failures drive full-index retry widening (D8)."""

from __future__ import annotations

from types import SimpleNamespace

from sevn.gateway.agent_turn import _tier_b_full_index_retry_warranted


def test_full_index_retry_warranted_on_failed_outcome_with_tool_failures() -> None:
    outcome = SimpleNamespace(
        status="failed",
        final_messages=(SimpleNamespace(text="history failed: timeout"),),
        had_tool_failures=True,
    )
    assert _tier_b_full_index_retry_warranted(no_answer_reason=None, outcome=outcome) is True


def test_full_index_retry_not_warranted_on_failed_without_tool_failures() -> None:
    outcome = SimpleNamespace(
        status="failed",
        final_messages=(SimpleNamespace(text="some report"),),
        had_tool_failures=False,
    )
    assert _tier_b_full_index_retry_warranted(no_answer_reason=None, outcome=outcome) is False


def test_full_index_retry_not_warranted_when_tools_succeeded_without_answer() -> None:
    outcome = SimpleNamespace(
        status="failed",
        final_messages=(),
        had_tool_failures=False,
        successful_tools_called=frozenset({"get_page_content"}),
    )
    assert _tier_b_full_index_retry_warranted(no_answer_reason=None, outcome=outcome) is False
