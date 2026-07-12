"""Wave W4: tier-B zero-tool grounding guard + self-architecture inject."""

from __future__ import annotations

from sevn.agent.executors.b_types import BTurnOutcome, ChannelPayload
from sevn.agent.grounding import (
    GROUNDING_TOOL_NAMES,
    apply_zero_tool_grounding_guard,
    asserts_false_fabrication,
    asserts_ungrounded_claims,
    claims_bound_tool_unavailable,
    is_routing_footer_query,
    is_self_architecture_query,
    tier_b_routing_footer_inject,
    tier_b_self_architecture_inject,
)
from sevn.gateway.agent_turn import _apply_tier_b_grounding_guard

_FABRICATED_CRON_TREE = (
    "Found it. Cron scheduling lives under src/sevn/tools/cron/ with "
    "`__init__.py`, `models.py`, `scheduler.py`, and `runner.py`. "
    "It uses APScheduler BlockingScheduler."
)

_FABRICATED_SERP_TABLE = (
    "serp returned 3 sources:\n\n| source | summary |\n| --- | --- |\n"
    "| example.com | political activities |"
)


def test_grounding_tool_names_cover_read_and_web() -> None:
    assert {"read", "glob", "search_in_file", "serp"} <= GROUNDING_TOOL_NAMES


def test_is_self_architecture_query_cron() -> None:
    assert is_self_architecture_query("where is the code for cron?")


def test_is_self_architecture_query_greeting_negative() -> None:
    assert not is_self_architecture_query("hello")


def test_asserts_ungrounded_claims_detects_fabricated_cron_tree() -> None:
    assert asserts_ungrounded_claims(_FABRICATED_CRON_TREE)


def test_asserts_ungrounded_claims_detects_serp_provenance() -> None:
    assert asserts_ungrounded_claims(_FABRICATED_SERP_TABLE)


def test_asserts_ungrounded_claims_ignores_bare_scheduler_class_names() -> None:
    """W3.2: APScheduler/class literals alone are not ungrounded-claims signals."""
    assert not asserts_ungrounded_claims("It uses APScheduler BlockingScheduler.")


def test_claims_bound_tool_unavailable_ignores_generic_dont_have() -> None:
    """W3.3: bare 'don't have' phrasing no longer triggers tool-unavailable detection."""
    text = "I don't have access to serp right now."
    assert claims_bound_tool_unavailable(text, frozenset({"serp"})) is None


def test_asserts_false_fabrication_ignores_bare_cant_see() -> None:
    """W3.4: bare 'can't see' phrasing no longer triggers fabrication detection."""
    assert not asserts_false_fabrication("I can't see any data from the last run.")


def test_fabricated_cron_tree_gets_unverified_prefix_zero_tools() -> None:
    out, applied = apply_zero_tool_grounding_guard(
        _FABRICATED_CRON_TREE,
        grounding_tools_called=frozenset(),
    )
    assert applied
    assert out.startswith("**Unverified**")
    assert "tools/cron" in out
    assert "APScheduler" in out


def test_fabricated_cron_tree_passes_when_read_ran() -> None:
    out, applied = apply_zero_tool_grounding_guard(
        _FABRICATED_CRON_TREE,
        grounding_tools_called=frozenset({"read"}),
    )
    assert not applied
    assert out == _FABRICATED_CRON_TREE


def test_fabricated_cron_tree_passes_when_glob_ran() -> None:
    _out, applied = apply_zero_tool_grounding_guard(
        _FABRICATED_CRON_TREE,
        grounding_tools_called=frozenset({"glob"}),
    )
    assert not applied


def test_serp_provenance_table_gets_unverified_prefix() -> None:
    out, applied = apply_zero_tool_grounding_guard(
        _FABRICATED_SERP_TABLE,
        grounding_tools_called=frozenset(),
    )
    assert applied
    assert "Unverified" in out


def test_routing_footer_query_detects_show_routing_question() -> None:
    assert is_routing_footer_query(
        "why isn't the routing footer shown after I toggled show_routing?"
    )


def test_routing_footer_inject_references_architecture_doc_not_hardcoded_paths() -> None:
    block = tier_b_routing_footer_inject()
    assert "SEVN-ARCHITECTURE.md" in block
    assert "routing_footer.py" not in block
    assert "telegram_show_routing_enabled" not in block
    assert "agent_turn.py" not in block


def test_append_output_truncation_notice_for_max_tokens() -> None:
    from sevn.agent.grounding import append_output_truncation_notice

    out = append_output_truncation_notice("partial answer", "max_tokens")
    assert "output token limit" in out
    assert append_output_truncation_notice("ok", "end_turn") == "ok"


def test_self_architecture_inject_references_architecture_doc_not_hardcoded_symbols() -> None:
    block = tier_b_self_architecture_inject()
    assert "SEVN-ARCHITECTURE.md" in block
    assert "do not name files" in block.lower()
    assert "sevn.triggers.cron" not in block
    assert "tools/cron" not in block
    assert "routing_footer.py" not in block


def test_apply_tier_b_grounding_guard_via_outcome() -> None:
    outcome = BTurnOutcome(
        status="completed",
        final_messages=(ChannelPayload(text=_FABRICATED_CRON_TREE),),
        escalation=None,
        rounds_used=0,
    )
    guarded, block_reason = _apply_tier_b_grounding_guard(_FABRICATED_CRON_TREE, outcome)
    assert block_reason is None
    assert guarded.startswith("**Unverified**")
