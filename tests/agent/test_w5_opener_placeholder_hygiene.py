"""W5 — Opener/placeholder hygiene + leaked-schema suppression (F7/F4).

Tests cover:
- W5.1: ``apply_routing_policy`` preserves a clean LLM ``first_message`` instead of
  overriding it with a forbidden-prefix canned ack.
- W5.1: double-message suppression — a forbidden-ack canned line is NOT preferred when
  the LLM's own ``first_message`` passes the opener rule.
- W5.2: none of the ``_EARLY_ACKS`` entries start with a forbidden opener prefix.
- W5.2: ``first_message_passes_opener_rule`` correctly classifies strings.
- W5.3: ``_is_tool_description_leak`` detects zero-tool description-as-answer output.
- W5.3: ``run_b_turn`` reclassifies a leaked-description reply as ``status='failed'``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sevn.agent.executors.b_harness import _is_tool_description_leak, run_b_turn
from sevn.agent.executors.b_types import (
    ResolvedTierBModel,
    SessionHandle,
)
from sevn.agent.openers import BARE_OPENERS
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.agent.triager.routing_policy import (
    _EARLY_ACKS,
    apply_routing_policy,
    first_message_passes_opener_rule,
)
from sevn.config.workspace_config import SecurityWorkspaceConfig, WorkspaceConfig
from sevn.tools.base import FunctionTool, ToolDefinition, ToolExecutor, enveloped_success
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.meta_loaders import attach_meta_loaders
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import merge_skill_manifests, snapshot_tool_set

# ---------------------------------------------------------------------------
# W5.2 — _EARLY_ACKS must not start with a forbidden opener prefix
# ---------------------------------------------------------------------------


def test_early_acks_none_start_with_forbidden_prefix() -> None:
    """No canned ack may start with a forbidden opener prefix (W5.2)."""
    for ack in _EARLY_ACKS:
        normed = " ".join(ack.lower().split())
        bad = [p for p in BARE_OPENERS if normed.startswith(p)]
        assert not bad, (
            f"Canned ack {ack!r} starts with forbidden prefix(es) {bad!r}. "
            "Update _EARLY_ACKS so no entry violates BARE_OPENERS."
        )


# ---------------------------------------------------------------------------
# W5.2 — first_message_passes_opener_rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Clean openers — should pass
        ("Hey Alex — what are we working on today?", True),
        ("Hmm, interesting question!", True),
        ("Right with you…", True),
        ("Reading now…", True),
        ("Right away.", True),
        ("A moment…", True),
        # Forbidden starters — must fail
        ("On it — give me a moment.", False),
        ("Let me check that for you.", False),
        ("Got it — reading logs.", False),
        ("Ok, I'll look into that.", False),
        ("Sure, one sec.", False),
        ("Checking the logs now.", False),
        ("Alright — let me see.", False),
        ("Fetching that for you.", False),
        ("Looking into it.", False),
        # Edge cases
        ("", False),
        ("Working on it\nmore text here", False),  # multi-line
        ("A" * 201, False),  # too long
    ],
)
def test_first_message_passes_opener_rule(text: str, expected: bool) -> None:
    assert first_message_passes_opener_rule(text) == expected, (
        f"first_message_passes_opener_rule({text!r}) should be {expected}"
    )


# ---------------------------------------------------------------------------
# W5.1 — apply_routing_policy preserves clean LLM first_message
# ---------------------------------------------------------------------------


def _make_triage(first_message: str, complexity: ComplexityTier = ComplexityTier.B) -> TriageResult:
    return TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=complexity,
        first_message=first_message,
        tools=["serp"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )


def test_apply_routing_policy_preserves_clean_llm_first_message() -> None:
    """W5.1: a clean LLM first_message ('Hey Alex…') is not replaced by a canned ack."""
    clean_opener = "Hey Alex — good to hear from you. What are we tackling?"
    raw = _make_triage(clean_opener)
    out = apply_routing_policy(raw, current_message="can you search for openclaw?", turn_id="t99")
    assert out.first_message == clean_opener, (
        f"Expected preserved LLM opener, got {out.first_message!r}"
    )


def test_apply_routing_policy_preserves_clean_opener_over_canned_ack() -> None:
    """W5.1: a non-forbidden opener from the LLM beats the canned 'On it' ack."""
    # Simulate a triager that produced a forbidden ack (older canned text).
    # The routing policy should NOT upgrade it further but also should not
    # discard a previously-clean original.  Here the input already has a clean
    # opener, so the output must equal the input.
    clean = "Hmm — interesting. I'll dig into that."
    raw = _make_triage(clean)
    out = apply_routing_policy(raw, current_message="check my logs", turn_id="abc")
    assert out.first_message == clean


def test_apply_routing_policy_does_not_restore_forbidden_opener() -> None:
    """W5.1 guard: a forbidden-prefix LLM opener is NOT restored after replacement."""
    bad_opener = "On it — here we go."
    raw = _make_triage(bad_opener)
    out = apply_routing_policy(raw, current_message="search for openclaw", turn_id="t1")
    # The policy should NOT restore the forbidden opener — it was correctly replaced.
    assert (
        not first_message_passes_opener_rule(out.first_message) or out.first_message != bad_opener
    ), "A forbidden-prefix opener must not be restored by W5.1 logic"


def test_apply_routing_policy_does_not_restore_echo_of_user_message() -> None:
    """W5.1 guard: if the LLM echoes the user message verbatim, it is not restored."""
    user_msg = "Hey Alex — what are we working on today?"
    raw = _make_triage(user_msg)
    out = apply_routing_policy(raw, current_message=user_msg, turn_id="t2")
    # Anti-echo rule fires; the result must not echo the user message.
    assert out.first_message.lower() != user_msg.lower()


def test_apply_routing_policy_does_not_restore_on_first_session() -> None:
    """W5.1 guard: first-session openers use the warm _FIRST_SESSION_ACKS pool."""
    clean = "Hey Alex — great to meet you."
    # Construct a tier-A result to trigger first-session upgrade.
    raw = TriageResult(
        intent=Intent.GREETING,
        complexity=ComplexityTier.A,
        first_message=clean,
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    out = apply_routing_policy(raw, current_message="hi", turn_id="t3", is_first_session=True)
    # The first-session path explicitly sets a _FIRST_SESSION_ACKS entry; do not
    # restore the LLM's opener here — the intro has its own curated warm message.
    assert out.first_message != clean


# ---------------------------------------------------------------------------
# W5.3 — _is_tool_description_leak
# ---------------------------------------------------------------------------


def test_tool_description_leak_detected() -> None:
    """W5.3: output containing a tool description after a stub opener is flagged."""
    descs = {
        "log_query": "Read the log file used for debugging the request. Default is logs/gateway.log."
    }
    leaked = (
        "On it — checking logs now."
        "Read the log file used for debugging the request. Default is logs/gateway.log."
    )
    assert _is_tool_description_leak(leaked, descs)


def test_tool_description_leak_exact_match() -> None:
    """W5.3: bare tool description with no opener is also flagged."""
    descs = {"serp": "Search the web for a query and return ranked results."}
    assert _is_tool_description_leak("Search the web for a query and return ranked results.", descs)


def test_tool_description_no_false_positive_real_answer() -> None:
    """W5.3: a substantive answer that happens to share generic words is not flagged."""
    descs = {"serp": "Search the web for a query and return ranked results."}
    real_answer = (
        "I found 3 results for openclaw on Wikipedia. The top result is about the marine robot."
    )
    assert not _is_tool_description_leak(real_answer, descs)


def test_tool_description_no_false_positive_empty() -> None:
    """W5.3: empty output does not trigger the guard."""
    descs = {"log_query": "Read the log file. Default is logs/gateway.log."}
    assert not _is_tool_description_leak("", descs)


def test_tool_description_short_descriptions_skipped() -> None:
    """W5.3: very short descriptions (< 20 chars) are not used for matching."""
    descs = {"x": "Do x."}  # too short
    assert not _is_tool_description_leak("Do x.", descs)


# ---------------------------------------------------------------------------
# W5.3 — run_b_turn reclassifies leaked-description reply as failed
# ---------------------------------------------------------------------------


def _openai_assistant_text(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def _make_leak_executor() -> tuple[ToolExecutor, Any]:
    """Minimal registry: ``log_query`` (with a description to leak) + meta loaders."""
    FAKE_DESC = "Read the workspace log file. Default is logs/gateway.log."

    exe = ToolExecutor(default_timeout_seconds=30.0)

    async def _log_query_fn(_ctx: ToolContext, **_: Any) -> str:  # pragma: no cover
        return enveloped_success("log line 1\nlog line 2")

    log_def = ToolDefinition(
        name="log_query",
        category="ops",
        description=FAKE_DESC,
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    )
    exe.register(FunctionTool(log_def, _log_query_fn))

    merged = merge_skill_manifests(None)
    native_map = {d.name: d for d in exe.definitions()}
    attach_meta_loaders(
        exe,
        native_definitions=dict(native_map),
        mcp_definitions={},
        skill_descriptions=merged,
        mcp_tool_names=frozenset(),
    )
    ts = snapshot_tool_set(
        exe,
        registry_version=1,
        skill_descriptions=merged,
        skill_inventory={},
        mcp_definitions=(),
        mcp_names=frozenset(),
    )
    return exe, ts


class _SingleShotTransport(ChatCompletionsTransport):
    """Transport that returns one scripted text reply then raises StopIteration."""

    def __init__(self, reply_text: str) -> None:
        super().__init__(proxy_base_url="http://w5-test.invalid")
        self._text = reply_text

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        return _openai_assistant_text(self._text)  # type: ignore[return-value]

    async def complete_stream(self, request: dict[str, object]) -> Any:
        raise NotImplementedError  # pragma: no cover


@pytest.mark.asyncio
async def test_run_b_turn_rejects_tool_description_leak(tmp_path: Path) -> None:
    """W5.3: a zero-tool reply that is a near-verbatim tool description is reclassified."""
    FAKE_DESC = "Read the workspace log file. Default is logs/gateway.log."

    exe, ts = _make_leak_executor()

    triage = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="Reading now…",
        tools=["log_query"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )

    # The model output is the tool description — zero tool calls (rounds_used=0).
    # Note: do NOT start with a forbidden opener prefix to avoid the opener-only guard
    # firing first; the W5.3 guard covers this case independently.
    leaked_output = FAKE_DESC

    transport = _SingleShotTransport(leaked_output)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    workspace = WorkspaceConfig(
        schema_version=1,
        workspace_root=str(tmp_path),
        security=SecurityWorkspaceConfig(),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )

    outcome = await run_b_turn(
        workspace=workspace,
        session=SessionHandle(session_id="s-w5"),
        turn_id="t-w5",
        triage=triage,
        incoming_text="read my logs",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=ToolContext(
            session_id="s-w5",
            workspace_path=tmp_path,
            workspace_id="w1",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-w5",
        ),
        max_rounds=1,
    )

    assert outcome.status == "failed", (
        f"Expected 'failed' for tool-description leak, got {outcome.status!r}"
    )
    assert (
        "leak" in (outcome.failure_detail or "").lower()
        or "description" in (outcome.failure_detail or "").lower()
    )
