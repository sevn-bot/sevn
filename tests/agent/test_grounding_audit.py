"""W5 — audit evidence grounding guard when log_query / transcript tools succeeded."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.usage import RunUsage

from sevn.agent.adapters.tier_b_hooks import TierBHookConfig, grounding_guard_after_model
from sevn.agent.executors.b_types import BTierDeps, BTurnOutcome, ChannelPayload, SteerInject
from sevn.agent.grounding import (
    EVIDENCE_TOOLS,
    apply_audit_evidence_guard,
    asserts_false_fabrication,
    steer_for_audit_evidence,
)
from sevn.gateway.agent_turn import _apply_tier_b_grounding_guard
from sevn.tools.base import ToolExecutor
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy

_FABRICATION_CONFESSION = (
    "I fabricated the audit answer — replay stub means I can't see any data and no tools ran."
)


def test_evidence_tools_include_log_query_and_read_transcript() -> None:
    assert {"log_query", "read_transcript", "history", "read"} <= EVIDENCE_TOOLS


def test_asserts_false_fabrication_detects_confession() -> None:
    assert asserts_false_fabrication(_FABRICATION_CONFESSION)


def test_asserts_false_fabrication_silent_on_normal_summary() -> None:
    assert not asserts_false_fabrication("log_query returned 3 ERROR lines in gateway.log.")


def test_apply_audit_evidence_guard_prefixes_when_log_query_succeeded() -> None:
    out, applied = apply_audit_evidence_guard(
        _FABRICATION_CONFESSION,
        successful_tools=frozenset({"log_query"}),
    )
    assert applied
    assert out.startswith("**Correction:** tool evidence exists this turn")
    assert "fabricated" in out


def test_apply_audit_evidence_guard_silent_without_evidence_tools() -> None:
    out, applied = apply_audit_evidence_guard(
        _FABRICATION_CONFESSION,
        successful_tools=frozenset({"serp"}),
    )
    assert not applied
    assert out == _FABRICATION_CONFESSION


def test_apply_audit_evidence_guard_codemode_log_query_trace() -> None:
    out, applied = apply_audit_evidence_guard(
        _FABRICATION_CONFESSION,
        successful_tools=frozenset({"run_code"}),
        codemode_bound_tools_called=frozenset({"log_query"}),
    )
    assert applied
    assert out.startswith("**Correction:**")


def test_apply_tier_b_grounding_guard_applies_audit_correction() -> None:
    outcome = BTurnOutcome(
        status="completed",
        final_messages=(ChannelPayload(text=_FABRICATION_CONFESSION),),
        escalation=None,
        rounds_used=1,
        successful_tools_called=frozenset({"read_transcript"}),
    )
    guarded, block_reason = _apply_tier_b_grounding_guard(_FABRICATION_CONFESSION, outcome)
    assert block_reason is None
    assert guarded.startswith("**Correction:**")


def test_steer_for_audit_evidence_mentions_evidence_tools() -> None:
    msg = steer_for_audit_evidence()
    assert "log_query" in msg
    assert "fabrication" in msg.lower()


def _hook_deps(*, steer: SteerInject | None = None) -> BTierDeps:
    return BTierDeps(
        tool_executor=ToolExecutor(),
        tool_context_template=ToolContext(
            session_id="s",
            workspace_path=Path("/tmp"),
            workspace_id="w",
            registry_version=1,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
        ),
        workspace_path=Path("/tmp"),
        registry_version=1,
        loaded_tools=set(),
        steer_buffer=steer,
    )


@pytest.mark.asyncio
async def test_grounding_hook_retries_on_fabrication_with_evidence_tools() -> None:
    steer = SteerInject()
    deps = _hook_deps(steer=steer)
    deps.successful_tools_called.add("log_query")
    ctx = RunContext(deps=deps, model=MagicMock(), usage=RunUsage())
    config = TierBHookConfig(
        provider_round_counter=[0],
        max_rounds=3,
        count_planning=False,
        bound_tool_names=frozenset(),
        triager_first_reply="",
    )
    response = ModelResponse(parts=[TextPart(content=_FABRICATION_CONFESSION)])
    with pytest.raises(ModelRetry):
        await grounding_guard_after_model(config, ctx, response)
    assert steer.pending_text is not None
    assert "log_query" in steer.pending_text
