"""Routing policy: greetings, identity tier B, anti-echo (`specs/13-rlm-triager.md`)."""

from __future__ import annotations

from typing import Any

from sevn.agent.openers import BARE_OPENERS
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.agent.triager.routing_policy import (
    _EARLY_ACKS,
    _FIRST_SESSION_ACKS,
    _GREETING_ACK_TOKENS,
    COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD,
    _merge_browser_tool_surface,
    _merge_file_ops_tools,
    _merge_package_install_tools,
    _merge_repo_file_ops_tools,
    _merge_session_recall_surface,
    apply_routing_policy,
    classify_greeting,
    default_early_ack,
    default_tier_a_reply,
    is_browser_tool_message,
    is_github_repo_eval_intent_message,
    is_identity_or_capability_message,
    is_lcm_status_message,
    is_live_factual_message,
    is_log_provenance_intent_message,
    is_obvious_continuation_message,
    is_package_install_message,
    is_pdf_file_pipeline_message,
    is_registry_capability_intent_message,
    is_registry_meta_howto_message,
    is_repo_code_intent_message,
    is_session_recall_message,
    is_skill_status_intent_message,
    is_strict_greeting_message,
    is_workspace_file_intent_message,
    prior_triage_indicates_in_progress,
    resolve_skill_status_target,
    try_fast_continuation_triage,
    try_fast_greeting_triage,
)
from sevn.agent.triager.run import _synthetic_schema_fallback


def _capture_info_logs() -> tuple[list[str], int, Any]:
    from loguru import logger as loguru_logger

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="INFO")
    return captured, sink_id, loguru_logger


def _intent_router_log_lines(captured: list[str]) -> list[str]:
    return [line for line in captured if "routing_policy.intent_router_applied" in line]


def test_greeting_ack_tokens_gracias_bye_ok_regression() -> None:
    """Regression: gracias/bye comma fix (c3eee11) and short-ack tokens stay distinct."""
    for token in ("gracias", "bye", "ok", "okay", "k"):
        assert token in _GREETING_ACK_TOKENS, token
    assert "graciasbye" not in _GREETING_ACK_TOKENS


def test_canned_acks_none_start_with_forbidden_prefix() -> None:
    """No canned ack may start with a forbidden opener prefix (routing_policy W5.2)."""
    for pool_name, pool in (
        ("_EARLY_ACKS", _EARLY_ACKS),
        ("_FIRST_SESSION_ACKS", _FIRST_SESSION_ACKS),
    ):
        for ack in pool:
            normed = " ".join(ack.lower().split())
            bad = [p for p in BARE_OPENERS if normed.startswith(p)]
            assert not bad, (
                f"{pool_name} entry {ack!r} starts with forbidden prefix(es) {bad!r}. "
                "Update the pool so no entry violates BARE_OPENERS."
            )


def test_identity_message_detected() -> None:
    assert is_identity_or_capability_message("who are you?")
    assert not is_strict_greeting_message("who are you?")


def test_llm_model_identity_phrasings_detected() -> None:
    """transcript-review-2026-06-22: "which LLM model are you using?" is an identity question.

    The old ``^which model`` pattern required "which model" adjacent and missed the "LLM"
    infix, so these fell to generic triage, bound ``read``, and were discarded by G0.
    """
    for msg in (
        "which LLM model are you using?",
        "what model are you using?",
        "which model are you using?",
        "what llm are you?",
        "what LLM are you running on?",
    ):
        assert is_identity_or_capability_message(msg), msg


def test_model_choice_questions_not_identity() -> None:
    """Model-*choice* questions (no self-reference) must not be coerced to identity."""
    assert not is_identity_or_capability_message("what model is best for coding?")
    assert not is_identity_or_capability_message("what is the bitcoin price right now?")


def test_strict_greeting_detected() -> None:
    assert is_strict_greeting_message("hello")
    assert is_strict_greeting_message("thanks!")


def test_exact_token_greetings_and_acks_fast_pathed() -> None:
    # Doubled/elongated spellings the ``\b`` regexes miss, plus short acks the
    # operator wants short-circuited before the slow triage LLM call.
    for msg in ("helloo", "hii", "heyy", "ok", "okay", "thanks", "thx", "ty", "bye", "K"):
        assert is_strict_greeting_message(msg), msg


def test_followups_not_greeting_fast_pathed() -> None:
    # Operator note: "so?" is a follow-up, never a greeting. Multi-word
    # substantive follow-ups must not be mistaken for greetings.
    for msg in ("so?", "so", "and?", "now", "ok now I see it", "so what about it"):
        assert not is_strict_greeting_message(msg), msg


def test_obvious_continuation_messages_detected() -> None:
    for msg in ("so?", "go ahead", "try again", "do it", "you just talk"):
        assert is_obvious_continuation_message(msg), msg


def test_substantive_followups_not_continuation_tokens() -> None:
    for msg in ("ok now I see it", "so what about it", "please fix the pdf render"):
        assert not is_obvious_continuation_message(msg), msg


def test_prior_triage_in_progress_gate() -> None:
    prior_busy = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=["read"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.8,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )
    assert prior_triage_indicates_in_progress(prior_busy)
    prior_idle = prior_busy.model_copy(update={"complexity": ComplexityTier.A, "tools": []})
    assert not prior_triage_indicates_in_progress(prior_idle)


def test_fast_continuation_replays_prior_routing() -> None:
    prior = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="Working.",
        tools=["read"],
        skills=["pdf"],
        mcp_servers_required=[],
        confidence=0.85,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )
    for msg in ("so?", "go ahead", "try again"):
        out = try_fast_continuation_triage(
            current_message=msg,
            prior=prior,
            turn_id="cont-1",
        )
        assert out is not None, msg
        assert out.intent == Intent.FOLLOWUP
        assert out.complexity == ComplexityTier.B
        assert out.tools == ["read"]
        assert out.skills == ["pdf"]
        assert out.replay_provider_history is True
        assert out.first_message.strip()


def test_fast_greeting_tier_a() -> None:
    result = try_fast_greeting_triage(current_message="hi", turn_id="t1")
    assert result is not None
    assert result.intent == Intent.GREETING
    assert result.complexity == ComplexityTier.A
    assert result.first_message.strip()
    assert result.first_message.lower() != "hi"


def test_echo_identity_coerced_to_tier_b() -> None:
    parsed = TriageResult(
        intent=Intent.GREETING,
        complexity=ComplexityTier.A,
        first_message="who are you?",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="who are you?",
        turn_id="turn-1",
    )
    assert out.complexity == ComplexityTier.B
    assert out.first_message.strip()
    assert out.first_message.lower() != "who are you?"


def test_empty_first_message_b_injected() -> None:
    parsed = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.5,
        requires_vision=False,
        requires_document=False,
        disregard=False,
        followup_anchor=None,
        permission_scope_narrowing=None,
    )
    out = apply_routing_policy(parsed, current_message="summarize tasks", turn_id="x")
    assert out.first_message.strip() == default_early_ack(turn_id="x")


def test_synthetic_fallback_has_ack() -> None:
    fb = _synthetic_schema_fallback(turn_id="fb")
    assert fb.complexity == ComplexityTier.B
    assert fb.first_message.strip()


def test_pdf_file_pipeline_intent_injects_file_ops_and_code_exec() -> None:
    msg = "extract the Wikipedia page into a PDF and send it"
    assert is_pdf_file_pipeline_message(msg)
    parsed = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=["list_dir", "process", "read", "run_skill_script", "send_file"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    out = apply_routing_policy(parsed, current_message=msg, turn_id="pdf-1")
    assert out.complexity == ComplexityTier.B
    for tool_id in (
        "glob",
        "search_in_file",
        "find_file",
        "file_info",
        "get_page_content",
        "terminal_run",
    ):
        assert tool_id in out.tools


def test_pdf_skill_selection_injects_file_pipeline_tools() -> None:
    parsed = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=["run_skill_script", "send_file"],
        skills=["pdf"],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="go ahead",
        turn_id="pdf-2",
    )
    assert "glob" in out.tools
    assert "terminal_run" in out.tools


def test_workspace_file_intent_injects_file_ops() -> None:
    assert is_workspace_file_intent_message("read USER.md and fix my name")
    parsed = TriageResult(
        intent=Intent.GREETING,
        complexity=ComplexityTier.A,
        first_message="On it.",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="change USER.md: Name: Alex",
        turn_id="file-1",
    )
    assert out.complexity == ComplexityTier.B
    assert "read" in out.tools
    assert "edit" in out.tools


def test_repo_code_intent_injects_repo_file_ops() -> None:
    assert is_repo_code_intent_message("do you have access to about-sevn.bot folder?")
    parsed = TriageResult(
        intent=Intent.GREETING,
        complexity=ComplexityTier.A,
        first_message="Checking.",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="what folders are on the root of sevn.bot?",
        turn_id="repo-1",
    )
    assert out.complexity == ComplexityTier.B
    assert "read" in out.tools
    assert "glob" in out.tools
    assert "list_dir" in out.tools
    assert "search_in_file" in out.tools
    assert "get_module_docstring" in out.tools
    assert "get_symbol_docstring" in out.tools
    assert "list_symbols" in out.tools


def test_source_code_in_message_forces_tier_b() -> None:
    assert is_repo_code_intent_message("Use list_dir on source_code/ and list top-level folders")
    parsed = TriageResult(
        intent=Intent.FOLLOWUP,
        complexity=ComplexityTier.A,
        first_message="On it.",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=1.0,
        requires_vision=False,
        requires_document=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="so what is in repo root folder?",
        turn_id="repo-2",
    )
    assert out.complexity == ComplexityTier.B
    assert "list_dir" in out.tools


def test_bootstrap_im_alex_forces_tier_b() -> None:
    parsed = TriageResult(
        intent=Intent.GREETING,
        complexity=ComplexityTier.A,
        first_message="Great to meet you, Alex!",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="I'm Alex",
        turn_id="boot-1",
        bootstrap_capture_active=True,
    )
    assert out.complexity == ComplexityTier.B
    assert out.first_message.strip()
    assert out.first_message != "I'm Alex"


def test_routing_policy_preserves_web_tools_on_log_mentions() -> None:
    """Log/error words in the message must not strip triager-scoped web tools."""
    parsed = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="Checking.",
        tools=["get_page_content", "serp", "glob"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="check the logs, what happened?",
        turn_id="no-strip-1",
    )
    assert "get_page_content" in out.tools
    assert "serp" in out.tools
    assert "glob" in out.tools


def test_routing_policy_preserves_web_on_casual_error_mention() -> None:
    parsed = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=["get_page_content", "serp"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="fetch headlines and log the error if the page fails",
        turn_id="no-strip-2",
    )
    assert "get_page_content" in out.tools
    assert "serp" in out.tools


def test_lcm_status_question_routes_to_lcm_skill_status_surface() -> None:
    assert is_lcm_status_message("What's in your LCM?")
    parsed = TriageResult(
        intent=Intent.GREETING,
        complexity=ComplexityTier.A,
        first_message="Sure.",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="What's in your LCM?",
        turn_id="lcm-1",
    )
    assert out.complexity == ComplexityTier.B
    assert "load_skill" in out.tools
    assert "run_skill_script" in out.tools
    assert "lcm" in out.skills


def test_session_recall_detector_and_merge_surface() -> None:
    """Recall phrasings detected; merge pins ``history`` first with memory/lcm backups."""
    assert is_session_recall_message("what did we talk about in the last session?")
    assert is_session_recall_message("summarize our conversation")
    assert not is_session_recall_message("what's the weather?")
    tools, skills = _merge_session_recall_surface(tools=[], skills=[])
    assert tools[0] == "history"  # primary recall path leads
    assert "memory_search" in tools  # backup
    assert "run_skill_script" in tools  # lcm backup (script execution)
    assert "lcm" in skills  # lcm backup (skill)


def test_session_recall_question_binds_history_first() -> None:
    """transcript-review-2026-06-22: recall questions bind history first (was memory_search/lcm)."""
    assert is_session_recall_message("what did we talk about in the last session?")
    parsed = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.A,
        first_message="On it.",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="what did we talk about in the last session?",
        turn_id="recall-1",
    )
    assert out.complexity == ComplexityTier.B
    assert out.tools[0] == "history"
    assert "memory_search" in out.tools
    assert "lcm" in out.skills


def test_package_install_message_detected() -> None:
    assert is_package_install_message("do option 1")
    assert is_package_install_message("uv sync --extra browser")
    assert not is_package_install_message("hello")


def test_browser_tool_message_detected() -> None:
    assert is_browser_tool_message("get a screenshot of https://example.com")
    assert is_browser_tool_message("capture a screenshot of the login page")
    assert is_browser_tool_message("Search nba.com")
    assert not is_browser_tool_message("hello")


def test_merge_package_install_tools_prefers_process() -> None:
    merged = _merge_package_install_tools(["terminal_run", "load_tool"])
    assert "process" in merged
    assert "terminal_run" not in merged
    assert "load_tool" in merged


def test_merge_browser_tool_surface() -> None:
    tools, skills = _merge_browser_tool_surface(["terminal_run", "process"], [])
    assert tools == ["browser", "load_tool", "send_file"]
    assert "terminal_run" not in tools
    assert "process" not in tools
    assert "browser-harness" not in skills  # retired platform skill ids must not appear


def test_package_install_routes_to_process_tool() -> None:
    parsed = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.A,
        first_message="Sure.",
        tools=["terminal_run"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="do option 1 — uv sync --extra browser",
        turn_id="install-1",
    )
    assert out.complexity == ComplexityTier.B
    assert "process" in out.tools
    assert "terminal_run" not in out.tools


def test_browser_tool_routes_to_browser_tool_surface() -> None:
    parsed = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.A,
        first_message="Sure.",
        tools=["terminal_run", "get_page_content"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="take a screenshot of https://www.coinbase.com/price/bitcoin",
        turn_id="pw-1",
    )
    assert out.complexity == ComplexityTier.B
    assert out.tools == ["browser", "load_tool", "send_file"]
    assert "browser" in out.tools
    assert "send_file" in out.tools
    assert ("play" + "wright" + "-browser") not in out.skills
    assert "terminal_run" not in out.tools
    assert "process" not in out.tools
    assert "get_page_content" not in out.tools


def test_low_confidence_short_c_clamps_to_b() -> None:
    """Vague short C decision below the confidence threshold clamps to B."""
    parsed = TriageResult.model_construct(
        intent=Intent.FOLLOWUP,
        complexity=ComplexityTier.C,
        first_message="On it.",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.78,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="all this needs to be fixed",
        turn_id="clamp-1",
    )
    assert out.complexity == ComplexityTier.B
    assert out.first_message.strip()


def test_low_confidence_followup_clamps_to_b_even_when_longer() -> None:
    """A longer FOLLOWUP with no concrete task still clamps when low-confidence."""
    parsed = TriageResult.model_construct(
        intent=Intent.FOLLOWUP,
        complexity=ComplexityTier.D,
        first_message="Working.",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.6,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="so what about all of the things from before then",
        turn_id="clamp-2",
    )
    assert out.complexity == ComplexityTier.B


def test_high_confidence_c_not_clamped() -> None:
    """A confident C decision survives the clamp regardless of length."""
    parsed = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.C,
        first_message="On it.",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="fix it",
        turn_id="clamp-3",
    )
    assert out.complexity == ComplexityTier.C


def test_low_confidence_long_new_request_not_clamped() -> None:
    """A long NEW_REQUEST is a real task; the clamp does not fire on it."""
    parsed = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.C,
        first_message="On it.",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.7,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message=(
            "please draft a multi-week launch plan covering pricing research, "
            "competitor analysis, a phased rollout schedule, and risk mitigation"
        ),
        turn_id="clamp-4",
    )
    assert out.complexity == ComplexityTier.C


def test_is_live_factual_message() -> None:
    assert is_live_factual_message("NBA finals score")
    assert is_live_factual_message("what's the weather today")
    assert not is_live_factual_message("hello")


def test_is_log_provenance_intent_message() -> None:
    assert is_log_provenance_intent_message(
        "check your logs, what tool did you use and which source?",
    )
    assert is_log_provenance_intent_message("which tools and skills were used?")
    assert not is_log_provenance_intent_message("NBA finals score")
    assert not is_log_provenance_intent_message("hello")


def test_apply_routing_policy_merges_log_provenance_surface() -> None:
    parsed = TriageResult.model_construct(
        intent=Intent.FOLLOWUP,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=["read"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
        disregard=False,
        replay_provider_history=True,
    )
    msg = "check your logs — what tool did you use?"
    out = apply_routing_policy(
        parsed,
        current_message=msg,
        turn_id="log-prov-1",
    )
    assert out.intent == Intent.FOLLOWUP
    assert "log_query" in out.tools
    assert "read_transcript" in out.tools
    assert "read" in out.tools
    assert out.replay_provider_history is False


def test_is_registry_capability_intent_message() -> None:
    assert is_registry_capability_intent_message("how does listregistry work?")
    assert is_registry_capability_intent_message("do you have a pdf skill?")
    assert is_registry_meta_howto_message("how does listregistry work?")
    assert not is_registry_capability_intent_message("where is the code for cron?")
    assert not is_registry_capability_intent_message("hello")


def test_apply_routing_policy_merges_registry_capability_surface() -> None:
    parsed = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=["read", "search_in_file"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="how does listregistry work?",
        turn_id="reg-howto-1",
    )
    assert "list_registry" in out.tools
    assert "read" in out.tools


def test_skill_status_intent_detects_last30days() -> None:
    msg = "what is last30days? what does it do? is it operational?"
    ids = frozenset({"last30days", "pdf"})
    assert (
        resolve_skill_status_target(
            msg,
            indexed_skill_ids=ids,
            triage_skills=["last30days"],
        )
        == "last30days"
    )
    assert is_skill_status_intent_message(
        msg,
        indexed_skill_ids=ids,
        triage_skills=["last30days"],
    )
    assert not is_skill_status_intent_message(
        "how does list_registry work?",
        indexed_skill_ids=ids,
        triage_skills=[],
    )


def test_apply_routing_policy_merges_skill_status_surface() -> None:
    parsed = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=["read"],
        skills=["last30days"],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )
    msg = "what is last30days? is it operational?"
    out = apply_routing_policy(
        parsed,
        current_message=msg,
        turn_id="l30-status-1",
        indexed_skill_ids=frozenset({"last30days", "pdf"}),
    )
    assert "list_registry" in out.tools
    assert "load_skill" in out.tools
    assert "run_skill_script" in out.tools
    assert "search_in_file" in out.tools
    assert "last30days" in out.skills


def test_apply_routing_policy_identity_merges_list_registry() -> None:
    parsed = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=["read"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="what can you do?",
        turn_id="identity-cap-1",
    )
    assert out.tools == ["list_registry"]
    assert "read" not in out.tools


def test_apply_routing_policy_identity_strips_model_picked_read() -> None:
    parsed = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=["read", "glob"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="what tools do you have?",
        turn_id="identity-cap-2",
    )
    assert out.tools == ["list_registry"]


def test_is_github_repo_eval_intent_message() -> None:
    msg = (
        "Check this: https://github.com/VectifyAI/PageIndex evaluate it. "
        "Can it be integrated in sevn as a skill?"
    )
    assert is_github_repo_eval_intent_message(msg)
    assert not is_github_repo_eval_intent_message("https://github.com/foo/bar")
    assert not is_github_repo_eval_intent_message("hello")


def test_apply_routing_policy_merges_github_repo_eval_surface() -> None:
    parsed = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=["get_page_content"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )
    msg = (
        "Check this: https://github.com/VectifyAI/PageIndex evaluate it. "
        "Can it be integrated in sevn as a skill?"
    )
    out = apply_routing_policy(parsed, current_message=msg, turn_id="gh-eval-1")
    assert "terminal_run" in out.tools
    assert "read" in out.tools
    assert "skill_management" in out.skills


def test_apply_routing_policy_merges_live_factual_tools() -> None:
    parsed = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=["serp"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="NBA finals score",
        turn_id="live-1",
    )
    assert "get_page_content" in out.tools
    assert "serp" in out.tools
    assert {"web_fetch", "web_search"} <= set(out.tools)


def test_apply_routing_policy_browser_plus_live_factual_includes_get_page_content() -> None:
    parsed = TriageResult.model_construct(
        intent=Intent.FOLLOWUP,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=["browser", "load_tool"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="use the browser tool for NBA finals score",
        turn_id="live-2",
    )
    assert ("play" + "wright" + "-browser") not in out.skills
    assert "browser" in out.tools
    assert "get_page_content" in out.tools
    assert "load_tool" in out.tools


def test_apply_routing_policy_merges_web_companions_for_get_page_content() -> None:
    parsed = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=["get_page_content"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )
    out = apply_routing_policy(
        parsed,
        current_message="Get today's news from DutchNews.nl",
        turn_id="web-1",
    )
    assert "get_page_content" in out.tools
    assert {"serp", "web_fetch", "web_search"} <= set(out.tools)


def test_tier_a_reply_pools_exact_sizes_w7() -> None:
    from sevn.agent.triager.tier_a_replies import (
        TIER_A_BYE_REPLIES,
        TIER_A_BYE_REPLY_COUNT,
        TIER_A_HELLO_REPLIES,
        TIER_A_HELLO_REPLY_COUNT,
        TIER_A_THANKS_REPLIES,
        TIER_A_THANKS_REPLY_COUNT,
        tier_a_bye_generic_replies,
        tier_a_bye_named_replies,
        tier_a_hello_generic_replies,
        tier_a_hello_named_replies,
        tier_a_thanks_generic_replies,
        tier_a_thanks_named_replies,
    )

    assert TIER_A_HELLO_REPLY_COUNT == 100
    assert len(TIER_A_HELLO_REPLIES) == 100
    assert len(tier_a_hello_generic_replies) == 50
    assert len(tier_a_hello_named_replies) == 50

    assert TIER_A_BYE_REPLY_COUNT == 50
    assert len(TIER_A_BYE_REPLIES) == 50
    assert len(tier_a_bye_generic_replies) == 25
    assert len(tier_a_bye_named_replies) == 25

    assert TIER_A_THANKS_REPLY_COUNT == 25
    assert len(TIER_A_THANKS_REPLIES) == 25
    assert len(tier_a_thanks_generic_replies) == 13
    assert len(tier_a_thanks_named_replies) == 12


def test_classify_greeting_three_categories_w7() -> None:
    assert classify_greeting("hi") == "hello"
    assert classify_greeting("hello") == "hello"
    assert classify_greeting("good morning") == "hello"
    assert classify_greeting("thanks") == "thanks"
    assert classify_greeting("thank you") == "thanks"
    assert classify_greeting("ok") == "thanks"
    assert classify_greeting("bye") == "bye"
    assert classify_greeting("see ya") == "bye"
    assert classify_greeting("who are you?") is None


def test_classify_greeting_elongations_via_normalization_w7() -> None:
    assert classify_greeting("heyyy") == "hello"
    assert classify_greeting("thanksss") == "thanks"
    assert is_strict_greeting_message("helloo")
    assert is_strict_greeting_message("hii")
    assert is_strict_greeting_message("heyy")


def test_default_tier_a_reply_category_pools_w7() -> None:
    hello = default_tier_a_reply(turn_id="h-1", kind="hello")
    thanks = default_tier_a_reply(turn_id="t-1", kind="thanks")
    bye = default_tier_a_reply(turn_id="b-1", kind="bye")
    assert (
        "?" in hello or "mind" in hello.lower() or hello.lower().startswith(("hi", "hey", "hello"))
    )
    assert thanks.lower().startswith(
        ("anytime", "you got", "happy", "no problem", "glad", "my pleasure")
    )
    assert "👋" in bye or bye.lower().startswith(
        ("see", "bye", "take", "goodbye", "later", "catch", "talk")
    )

    named_thanks = [
        default_tier_a_reply(turn_id=f"tn-{idx}", operator_name="Alex", kind="thanks")
        for idx in range(200)
    ]
    named_bye = [
        default_tier_a_reply(turn_id=f"bn-{idx}", operator_name="Alex", kind="bye")
        for idx in range(200)
    ]
    assert any("Alex" in reply for reply in named_thanks)
    assert any("Alex" in reply for reply in named_bye)
    assert all("{name}" not in reply for reply in named_thanks + named_bye)


def test_fast_greeting_triage_uses_strict_category_replies_w8() -> None:
    thanks = try_fast_greeting_triage(current_message="thanks", turn_id="ft-1")
    assert thanks is not None
    assert is_strict_greeting_message(thanks.first_message)

    bye = try_fast_greeting_triage(current_message="bye", turn_id="fb-1")
    assert bye is not None
    assert is_strict_greeting_message(bye.first_message)


def test_default_tier_a_reply_never_leaves_name_placeholder() -> None:
    for kind in ("hello", "thanks", "bye"):
        for idx in range(200):
            reply = default_tier_a_reply(turn_id=f"turn-{kind}-{idx}", kind=kind)
            assert "{name}" not in reply
            assert reply.strip()


def test_default_tier_a_reply_uses_operator_name_from_user_md() -> None:
    replies = [
        default_tier_a_reply(turn_id=f"tier-a-named-{idx}", operator_name="Alex", kind="hello")
        for idx in range(200)
    ]
    assert any("Alex" in reply for reply in replies)
    assert all("{name}" not in reply for reply in replies)
    assert all(len(reply) <= 100 for reply in replies)


def test_pdf_question_does_not_force_file_pipeline() -> None:
    """W3.5/W3.8: informational PDF questions must not trigger the pipeline router."""
    assert not is_pdf_file_pipeline_message("what's a pdf?")


def test_general_code_help_not_repo_code_intent() -> None:
    """W3.6/W3.8: generic coding-help questions must not force repo-code intent."""
    assert not is_repo_code_intent_message("where is the bug in my code")


def test_repo_code_intent_cron_question_w4_unified_classifier() -> None:
    """W4.2/W4.4: self-architecture cron questions use the single repo-code classifier."""
    assert is_repo_code_intent_message("where is the code for cron?")


def test_repo_code_intent_greeting_negative_w4() -> None:
    """W4.4: greetings must not trigger repo-code / self-architecture intent."""
    assert not is_repo_code_intent_message("hello")


def test_intent_router_applied_log_when_routing_changes_w10() -> None:
    """W10: structured log fires when an intent router changes tier or tools."""
    captured, sink_id, loguru_logger = _capture_info_logs()
    try:
        parsed = TriageResult(
            intent=Intent.GREETING,
            complexity=ComplexityTier.A,
            first_message="Sure.",
            tools=[],
            skills=[],
            mcp_servers_required=[],
            confidence=0.9,
            requires_vision=False,
            requires_document=False,
        )
        out = apply_routing_policy(
            parsed,
            current_message="read USER.md and fix my name",
            turn_id="router-log-1",
        )
        assert out.complexity == ComplexityTier.B
        assert "read" in out.tools
        lines = _intent_router_log_lines(captured)
        assert len(lines) == 1
        assert "router=is_workspace_file_intent_message" in lines[0]
        assert "changed_tier=True" in lines[0]
        assert "added_tools=" in lines[0]
    finally:
        loguru_logger.remove(sink_id)


def test_intent_router_applied_log_when_only_tools_change_w10() -> None:
    """W10: pdf skill pipeline logs when tools are added without a tier change."""
    captured, sink_id, loguru_logger = _capture_info_logs()
    try:
        parsed = TriageResult(
            intent=Intent.NEW_REQUEST,
            complexity=ComplexityTier.B,
            first_message="On it.",
            tools=["run_skill_script", "send_file"],
            skills=["pdf"],
            mcp_servers_required=[],
            confidence=0.9,
            requires_vision=False,
            requires_document=False,
        )
        out = apply_routing_policy(
            parsed,
            current_message="go ahead",
            turn_id="router-log-2",
        )
        assert out.complexity == ComplexityTier.B
        assert "glob" in out.tools
        lines = _intent_router_log_lines(captured)
        assert len(lines) == 1
        assert "router=is_pdf_file_pipeline_message" in lines[0]
        assert "changed_tier=False" in lines[0]
        assert "glob" in lines[0]
    finally:
        loguru_logger.remove(sink_id)


def test_intent_router_applied_log_skipped_when_routing_unchanged_w10() -> None:
    """W10: no log when the router matches but tier/tools/skills are already satisfied."""
    captured, sink_id, loguru_logger = _capture_info_logs()
    try:
        repo_tools = _merge_repo_file_ops_tools([])
        parsed = TriageResult(
            intent=Intent.NEW_REQUEST,
            complexity=ComplexityTier.B,
            first_message="On it.",
            tools=repo_tools,
            skills=[],
            mcp_servers_required=[],
            confidence=0.9,
            requires_vision=False,
            requires_document=False,
        )
        out = apply_routing_policy(
            parsed,
            current_message="where is the code for cron?",
            turn_id="router-log-3",
        )
        assert out.complexity == ComplexityTier.B
        assert set(out.tools) == set(repo_tools)
        assert not _intent_router_log_lines(captured)
    finally:
        loguru_logger.remove(sink_id)


def test_intent_router_applied_log_absent_for_non_matching_message_w10() -> None:
    """W10: plain greetings must not emit intent-router applied events."""
    captured, sink_id, loguru_logger = _capture_info_logs()
    try:
        parsed = TriageResult(
            intent=Intent.GREETING,
            complexity=ComplexityTier.A,
            first_message="Hi!",
            tools=[],
            skills=[],
            mcp_servers_required=[],
            confidence=0.9,
            requires_vision=False,
            requires_document=False,
        )
        out = apply_routing_policy(
            parsed,
            current_message="hello",
            turn_id="router-log-4",
        )
        assert out.complexity == ComplexityTier.A
        assert not _intent_router_log_lines(captured)
    finally:
        loguru_logger.remove(sink_id)


def test_intent_router_applied_logs_cover_remaining_routers_w10() -> None:
    """W10: memorize, lcm, repo-code, and evolution routers emit when they change routing."""
    cases: tuple[tuple[str, TriageResult, str], ...] = (
        (
            "Memorize this: I prefer ls.",
            TriageResult(
                intent=Intent.GREETING,
                complexity=ComplexityTier.A,
                first_message="Sure.",
                tools=[],
                skills=[],
                mcp_servers_required=[],
                confidence=0.9,
                requires_vision=False,
                requires_document=False,
            ),
            "is_memorize_message",
        ),
        (
            "What's in your LCM?",
            TriageResult(
                intent=Intent.NEW_REQUEST,
                complexity=ComplexityTier.A,
                first_message="Sure.",
                tools=[],
                skills=[],
                mcp_servers_required=[],
                confidence=0.9,
                requires_vision=False,
                requires_document=False,
            ),
            "is_lcm_status_message",
        ),
        (
            "do option 1",
            TriageResult(
                intent=Intent.NEW_REQUEST,
                complexity=ComplexityTier.A,
                first_message="Sure.",
                tools=["terminal_run"],
                skills=[],
                mcp_servers_required=[],
                confidence=0.9,
                requires_vision=False,
                requires_document=False,
            ),
            "is_package_install_message",
        ),
        (
            "screenshot https://example.com",
            TriageResult(
                intent=Intent.NEW_REQUEST,
                complexity=ComplexityTier.A,
                first_message="Sure.",
                tools=["terminal_run"],
                skills=[],
                mcp_servers_required=[],
                confidence=0.9,
                requires_vision=False,
                requires_document=False,
            ),
            "is_browser_tool_message",
        ),
        (
            "what folders are on the root of sevn.bot?",
            TriageResult(
                intent=Intent.GREETING,
                complexity=ComplexityTier.A,
                first_message="Checking.",
                tools=[],
                skills=[],
                mcp_servers_required=[],
                confidence=0.9,
                requires_vision=False,
                requires_document=False,
            ),
            "is_repo_code_intent_message",
        ),
        (
            "fix issue #42",
            TriageResult.model_construct(
                intent=Intent.NEW_REQUEST,
                complexity=ComplexityTier.A,
                first_message="On it.",
                tools=[],
                skills=[],
                mcp_servers_required=[],
                confidence=0.9,
                requires_vision=False,
                requires_document=False,
                disregard=False,
            ),
            "is_evolution_fix_intent_message",
        ),
    )
    for idx, (message, parsed, router_name) in enumerate(cases):
        captured, sink_id, loguru_logger = _capture_info_logs()
        try:
            out = apply_routing_policy(
                parsed,
                current_message=message,
                turn_id=f"router-log-multi-{idx}",
            )
            assert out.complexity == ComplexityTier.B
            lines = _intent_router_log_lines(captured)
            assert len(lines) == 1, (message, lines)
            assert f"router={router_name}" in lines[0]
            assert "changed_tier=True" in lines[0] or "added_tools=" in lines[0]
        finally:
            loguru_logger.remove(sink_id)


def test_intent_router_applied_log_skipped_for_premerged_workspace_tools_w10() -> None:
    """W10: workspace-file router stays silent when file-ops tools are already present."""
    captured, sink_id, loguru_logger = _capture_info_logs()
    try:
        parsed = TriageResult(
            intent=Intent.NEW_REQUEST,
            complexity=ComplexityTier.B,
            first_message="On it.",
            tools=_merge_file_ops_tools([]),
            skills=[],
            mcp_servers_required=[],
            confidence=0.9,
            requires_vision=False,
            requires_document=False,
        )
        out = apply_routing_policy(
            parsed,
            current_message="read USER.md and fix my name",
            turn_id="router-log-5",
        )
        assert out.complexity == ComplexityTier.B
        assert not _intent_router_log_lines(captured)
    finally:
        loguru_logger.remove(sink_id)


# --- W1 RED (DP3): retired driver → browser_tool renames (green after W5) ---


def test_is_browser_tool_message_renamed_and_behaves() -> None:
    """DP3: is_browser_tool_message exists and mirrors prior screenshot/browser detection."""
    from sevn.agent.triager.routing_policy import is_browser_tool_message

    assert is_browser_tool_message("get a screenshot of https://example.com")
    assert is_browser_tool_message("capture a screenshot of the login page")
    assert is_browser_tool_message("Search nba.com")
    assert not is_browser_tool_message("hello")


def test_merge_browser_tool_surface_renamed() -> None:
    """DP3: _merge_browser_tool_surface replaces the retired merge helper name."""
    from sevn.agent.triager import routing_policy as rp

    _old_merge = "_merge_" + "play" + "wright" + "_browser_surface"
    assert hasattr(rp, "_merge_browser_tool_surface")
    assert not hasattr(rp, _old_merge)
    tools, skills = rp._merge_browser_tool_surface(["terminal_run", "process"], [])
    assert tools == ["browser", "load_tool", "send_file"]
    assert ("play" + "wright" + "-browser") not in skills


def test_retired_routing_symbols_removed() -> None:
    """DP3: old driver-named routing helpers are absent after rename."""
    from sevn.agent.triager import routing_policy as rp

    tag = "play" + "wright"
    assert not hasattr(rp, f"is_{tag}_browser_message")
    assert not hasattr(rp, f"_{tag.upper()}_BROWSER_PATTERNS")
    assert not hasattr(rp, f"_{tag.upper()}_BROWSER_TOOL_IDS")
    assert hasattr(rp, "_BROWSER_TOOL_PATTERNS")
    assert hasattr(rp, "_BROWSER_TOOL_TOOL_IDS")
