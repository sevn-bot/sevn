"""Wave 2 - grounding & loop integrity (live-session PDF plan P5/P6/P8)."""

from __future__ import annotations

from pydantic_ai.messages import TextPart, ToolCallPart

from sevn.agent.adapters.tool_part_filter import (
    RECOVERY_WIDEN_FAILURE_THRESHOLD,
    MutableToolAllowlist,
    filter_tool_call_parts,
)
from sevn.agent.executors import b_harness as b_harness_mod
from sevn.agent.executors.b_types import BTurnOutcome, ChannelPayload
from sevn.agent.grounding import (
    apply_file_delivery_grounding_guard,
    apply_live_factual_grounding_guard,
    claims_file_delivery_success,
    claims_live_factual_content,
    steer_for_dropped_tool_call,
    steer_for_triager_bound_tools_unused,
)
from sevn.gateway.agent_turn import _apply_tier_b_grounding_guard


def test_claims_file_delivery_success_detects_pdf_send_claim() -> None:
    assert claims_file_delivery_success("PDF written to workspace. Sending it now.")


def test_claims_live_factual_content_detects_nba_score() -> None:
    assert claims_live_factual_content("The NBA Finals series is tied 1-1 after Game 2.")


def test_claims_live_factual_content_ignores_motion_promise() -> None:
    assert not claims_live_factual_content("I'll check the NBA Finals score now.")


def test_apply_live_factual_grounding_guard_blocks_without_web_tools() -> None:
    claim = "The NBA Finals series is tied 1-1 after Game 2."
    _out, blocked = apply_live_factual_grounding_guard(
        claim,
        successful_tools_called=frozenset({"glob"}),
    )
    assert blocked


def test_apply_live_factual_grounding_guard_passes_after_get_page_content() -> None:
    claim = "The NBA Finals series is tied 1-1 after Game 2."
    out, blocked = apply_live_factual_grounding_guard(
        claim,
        successful_tools_called=frozenset({"get_page_content"}),
    )
    assert not blocked
    assert out == claim


def test_apply_live_factual_grounding_guard_passes_after_log_query() -> None:
    claim = "The NBA Finals series is tied 1-1 after Game 2."
    out, blocked = apply_live_factual_grounding_guard(
        claim,
        successful_tools_called=frozenset({"log_query"}),
    )
    assert not blocked
    assert out == claim


def test_steer_for_triager_bound_tools_unused_browser_tool_hint() -> None:
    """DP3 residue: unused-bound steer names the native browser tool (playwright-browser gone)."""
    steer = steer_for_triager_bound_tools_unused(["browser"], [])
    assert "browser" in steer
    assert "do not" in steer.lower()


def test_apply_file_delivery_grounding_guard_blocks_without_send_file() -> None:
    claim = "PDF written to workspace. Sending it now."
    _out, blocked = apply_file_delivery_grounding_guard(
        claim,
        successful_tools_called=frozenset(),
        had_tool_failures=True,
    )
    assert blocked


def test_apply_file_delivery_grounding_guard_passes_when_send_file_ran() -> None:
    claim = "PDF written to workspace. Sending it now."
    out, blocked = apply_file_delivery_grounding_guard(
        claim,
        successful_tools_called=frozenset({"send_file"}),
    )
    assert not blocked
    assert out == claim


def test_apply_tier_b_grounding_guard_blocks_fabricated_file_delivery() -> None:
    claim = "On it — sending the file now."
    outcome = BTurnOutcome(
        status="completed",
        final_messages=(ChannelPayload(text=claim),),
        escalation=None,
        rounds_used=1,
        had_tool_failures=True,
        last_tool_failure_name="run_skill_script",
    )
    guarded, block_reason = _apply_tier_b_grounding_guard(claim, outcome)
    assert block_reason == "fabricated_file_delivery"
    assert guarded == ""


def test_is_execution_filler_completion_flags_zero_round_pipeline_filler() -> None:
    assert b_harness_mod._is_execution_filler_completion(
        rounds_used=0,
        text="On it — I'll run the full pipeline.",
        opener="On it — I'll run the full pipeline.",
        triage_tools=("run_skill_script", "send_file"),
    )


def test_filter_tool_call_parts_invokes_on_dropped() -> None:
    dropped: list[str] = []
    parts = [
        TextPart(content="ok"),
        ToolCallPart(tool_name="not_a_real_tool", args="{}", tool_call_id="x"),
    ]
    kept = filter_tool_call_parts(
        parts,
        allowed_tool_names=frozenset({"read"}),
        on_dropped=dropped.append,
    )
    assert [type(p).__name__ for p in kept] == ["TextPart"]
    assert dropped == ["not_a_real_tool"]


def test_filter_tool_call_parts_auto_grants_registry_tool() -> None:
    granted: list[str] = []
    allow = MutableToolAllowlist(
        base=frozenset({"read", "run_skill_script"}),
        registry_names=frozenset({"read", "run_skill_script", "terminal_run", "glob"}),
    )
    parts = [
        ToolCallPart(tool_name="terminal_run", args="{}", tool_call_id="t1"),
        ToolCallPart(tool_name="glob", args="{}", tool_call_id="g1"),
    ]
    kept = filter_tool_call_parts(
        parts,
        allowed_tool_names=allow,
        on_granted=granted.append,
    )
    assert [p.tool_name for p in kept] == ["terminal_run", "glob"]  # type: ignore[attr-defined]
    assert set(granted) == {"terminal_run", "glob"}
    assert {"terminal_run", "glob"} <= allow.effective


def test_codemode_blocks_web_tool_autogrants() -> None:
    allow = MutableToolAllowlist(
        base=frozenset({"get_page_content", "run_code"}),
        registry_names=frozenset({"get_page_content", "serp", "glob", "run_code"}),
        codemode_blocks_web_autogrants=True,
    )
    assert allow.grant_registry_tool("serp") is False
    assert "serp" not in allow.effective
    assert allow.grant_registry_tool("glob") is True
    assert "glob" in allow.effective


def test_mutable_allowlist_widens_diagnostics() -> None:
    allow = MutableToolAllowlist(
        base=frozenset({"run_skill_script"}),
        registry_names=frozenset({"read", "process", "run_skill_script"}),
    )
    allow.widen_diagnostics()
    assert {"read", "process"} <= allow.effective


def test_steer_for_dropped_tool_call_lists_available_tools() -> None:
    msg = steer_for_dropped_tool_call(
        "not_a_real_tool", available_tools=frozenset({"read", "send_file"})
    )
    assert "TOOL_NOT_PROVISIONED" in msg
    assert "not_a_real_tool" in msg
    assert "read" in msg


def test_recovery_widen_threshold_is_two() -> None:
    assert RECOVERY_WIDEN_FAILURE_THRESHOLD == 2
