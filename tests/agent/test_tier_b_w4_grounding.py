"""W4 — skill playbook prompts, audit honesty guards, list_dir embellishment (3d3160)."""

from __future__ import annotations

from sevn.agent.grounding import (
    apply_audit_evidence_guard,
    apply_live_factual_grounding_guard,
    claims_list_dir_embellishment,
    claims_unattempted_tool_failure,
    steer_for_false_tool_failure_claim,
    tools_attempted_from_call_counts,
)

_BC75F9_AUDIT = (
    "I tried load_tool(search_in_file) but it failed — search_in_file is not provisioned."
)

_MSG_3D3160_TABLE = (
    "| Name | Size | Modified |\n"
    "| --- | --- | --- |\n"
    "| MEMORY.md | 12 KB | 2026-06-01 |\n"
    "| skills/ | dir | — |\n"
)


def test_claims_unattempted_tool_failure_bc75f9_shape() -> None:
    assert (
        claims_unattempted_tool_failure(_BC75F9_AUDIT, tools_attempted=frozenset())
        == "search_in_file"
    )


def test_claims_unattempted_tool_failure_silent_when_tool_dispatched() -> None:
    assert (
        claims_unattempted_tool_failure(
            "search_in_file returned ok=false for path.",
            tools_attempted=frozenset({"search_in_file"}),
        )
        is None
    )


def test_apply_audit_evidence_guard_false_load_tool_without_dispatch() -> None:
    out, applied = apply_audit_evidence_guard(
        _BC75F9_AUDIT,
        successful_tools=frozenset(),
        tools_attempted=frozenset(),
    )
    assert applied
    assert "no dispatch record" in out.lower()
    assert "read_transcript" in out


def test_tools_attempted_from_call_counts_parses_load_tool_target() -> None:
    attempted = tools_attempted_from_call_counts(
        {'load_tool:{"name": "search_in_file"}': 1},
    )
    assert attempted == frozenset({"load_tool", "search_in_file"})


def test_claims_list_dir_embellishment_3d3160_table_shape() -> None:
    assert claims_list_dir_embellishment(_MSG_3D3160_TABLE)


def test_apply_live_factual_guard_allows_plain_list_dir_names() -> None:
    plain = "- MEMORY.md\n- skills/\n- sevn.json"
    out, blocked = apply_live_factual_grounding_guard(
        plain,
        successful_tools_called=frozenset({"list_dir"}),
    )
    assert not blocked
    assert out == plain


def test_apply_live_factual_guard_blocks_list_dir_table_embellishment() -> None:
    _out, blocked = apply_live_factual_grounding_guard(
        _MSG_3D3160_TABLE,
        successful_tools_called=frozenset({"list_dir"}),
    )
    assert blocked


def test_steer_for_false_tool_failure_claim_names_log_tools() -> None:
    msg = steer_for_false_tool_failure_claim()
    assert "read_transcript" in msg
    assert "log_query" in msg
