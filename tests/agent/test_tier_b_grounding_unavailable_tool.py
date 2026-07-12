"""W2 — grounding guard: never ship "I can't call `<tool>`" (F2/F3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sevn.agent.adapters.tier_b_tools import _dispatch_tool
from sevn.agent.executors.b_harness import run_b_turn
from sevn.agent.executors.b_types import (
    BTierDeps,
    ResolvedTierBModel,
    SessionHandle,
    SteerInject,
)
from sevn.agent.grounding import (
    claims_bound_tool_unavailable,
    steer_for_direct_tool_call,
)
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.config.workspace_config import SecurityWorkspaceConfig, WorkspaceConfig
from sevn.gateway.agent_turn import _tier_b_full_index_retry_warranted
from sevn.tools.base import FunctionTool, ToolDefinition, ToolExecutor
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.meta_loaders import attach_meta_loaders
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import merge_skill_manifests, snapshot_tool_set


def test_claims_bound_tool_unavailable_detects_serp_confabulation() -> None:
    text = "serp isn't in my current callable function list."
    assert claims_bound_tool_unavailable(text, frozenset({"serp"})) == "serp"


def test_claims_bound_tool_unavailable_ignores_unbound_tool() -> None:
    text = "serp isn't in my current callable function list."
    assert claims_bound_tool_unavailable(text, frozenset({"read"})) is None


def test_steer_for_direct_tool_call_names_tool() -> None:
    msg = steer_for_direct_tool_call("serp")
    assert "`serp`" in msg
    assert "run_skill_script" in msg


def _openai_assistant_text(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class _SingleShotTransport(ChatCompletionsTransport):
    def __init__(self, reply_text: str) -> None:
        super().__init__(proxy_base_url="http://w2-test.invalid")
        self._text = reply_text

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        return _openai_assistant_text(self._text)  # type: ignore[return-value]

    async def complete_stream(self, request: dict[str, object]) -> Any:
        raise NotImplementedError  # pragma: no cover


def _make_serp_executor() -> tuple[ToolExecutor, Any]:
    exe = ToolExecutor(default_timeout_seconds=30.0)

    async def _serp_fn(_ctx: ToolContext, **_: Any) -> str:  # pragma: no cover
        return '{"ok": true, "data": {"results": []}}'

    serp_def = ToolDefinition(
        name="serp",
        category="web",
        description="Search the web for a query and return ranked results.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    )
    exe.register(FunctionTool(serp_def, _serp_fn))

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


@pytest.mark.asyncio
async def test_run_b_turn_rejects_serp_unavailable_claim(tmp_path: Path) -> None:
    """W2.1: a fabricated 'serp isn't callable' answer becomes a failed retry."""
    exe, ts = _make_serp_executor()
    confabulation = "serp isn't in my current callable function list."

    triage = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="Searching now…",
        tools=["serp"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )

    transport = _SingleShotTransport(confabulation)
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
    steer = SteerInject()

    outcome = await run_b_turn(
        workspace=workspace,
        session=SessionHandle(session_id="s-w2"),
        turn_id="t-w2",
        triage=triage,
        incoming_text="search wikipedia openclaw",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=steer,
        tool_context=ToolContext(
            session_id="s-w2",
            workspace_path=tmp_path,
            workspace_id="w1",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-w2",
        ),
        max_rounds=1,
    )

    assert outcome.status == "failed"
    assert outcome.failure_detail == "tool_unavailable_claim:serp"
    assert not outcome.final_messages
    assert steer.pop_pending() == steer_for_direct_tool_call("serp")
    assert _tier_b_full_index_retry_warranted(no_answer_reason=None, outcome=outcome) is True


def _deps(*, steer: SteerInject | None = None) -> BTierDeps:
    ctx = ToolContext(
        session_id="s",
        workspace_path=Path("/tmp"),
        workspace_id="w",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )
    return BTierDeps(
        tool_executor=ToolExecutor(),
        tool_context_template=ctx,
        workspace_path=Path("/tmp"),
        registry_version=1,
        steer_buffer=steer,
    )


def _run_ctx(deps: BTierDeps) -> MagicMock:
    ctx = MagicMock()
    ctx.deps = deps
    return ctx


@pytest.mark.asyncio
async def test_skill_is_actually_tool_first_failure_injects_steer() -> None:
    """W2.2: first run_skill_script-on-tool failure steers direct call, not just error."""
    steer = SteerInject()
    deps = _deps(steer=steer)
    definition = ToolDefinition(
        name="run_skill_script",
        category="skills",
        description="run skill",
        parameters={"type": "object", "properties": {"skill": {"type": "string"}}},
    )
    payload = {"skill": "serp"}
    envelope = json.dumps(
        {
            "ok": False,
            "code": ToolResultCode.SKILL_IS_ACTUALLY_TOOL,
            "error": "serp is a tool",
            "did_you_mean_tool": "serp",
        },
    )
    deps.tool_executor.dispatch = AsyncMock(return_value=envelope)  # type: ignore[method-assign]

    raw = await _dispatch_tool(_run_ctx(deps), definition, payload)

    assert "SKILL_IS_ACTUALLY_TOOL" in raw
    assert steer.pop_pending() == steer_for_direct_tool_call("serp")
    assert deps.escalation is None
