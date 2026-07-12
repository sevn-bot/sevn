"""Tier C/D opt-in λ-RLM path (`specs/21-executor-tier-cd.md` §2.5; Wave 8 gate)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.executors.b_types import SessionHandle
from sevn.agent.executors.cd_harness import NoOpPlanGate, run_cd_turn
from sevn.agent.executors.cd_types import ResolvedCdOuterModels
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.config.defaults import LAMBDA_RLM_DEGRADED_PLAN_SPLIT_MESSAGE
from sevn.config.workspace_config import parse_workspace_config
from sevn.tools.base import FunctionTool, ToolDefinition, ToolExecutor, enveloped_success
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import ToolSet, merge_skill_manifests, snapshot_tool_set


def _assistant_json(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": json.dumps(obj)}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class _SynthOnlyTransport(ChatCompletionsTransport):
    def __init__(self) -> None:
        super().__init__(proxy_base_url="http://tier-cd-lambda.test.invalid")
        self.phases: list[str] = []

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        raw = request["messages"]
        assert isinstance(raw, list)
        body = json.loads(str(raw[0].get("content", "")))
        phase = str(body.get("__sevn_cd_phase", ""))
        self.phases.append(phase)
        if phase == "synthesize":
            return _assistant_json({"final_text": "λ done."})
        return _assistant_json({})


def _make_workspace(*, tmp: Path, allowlist: list[str]) -> object:
    return parse_workspace_config(
        {
            "schema_version": 1,
            "workspace_root": str(tmp),
            "security": {},
            "rlm": {"c_d_backend": "lambda_rlm", "lambda_tool_allowlist": allowlist},
            "executors": {"tier_cd": {"lambda_rlm": {"enabled": True}}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )


def _triage_c() -> TriageResult:
    return TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.C,
        first_message="working",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        permission_scope_narrowing=None,
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )


def _minimal_tooling() -> tuple[ToolExecutor, ToolSet]:
    exe = ToolExecutor(default_timeout_seconds=5.0)

    async def _noop(_ctx: ToolContext) -> str:
        return enveloped_success({})

    d = ToolDefinition(
        name="tick",
        category="meta",
        description="tick",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    )
    exe.register(FunctionTool(d, _noop))
    merged = merge_skill_manifests(None)
    return exe, snapshot_tool_set(
        exe,
        registry_version=1,
        skill_descriptions=merged,
        skill_inventory={},
        mcp_definitions=(),
        mcp_names=frozenset(),
    )


@pytest.mark.asyncio
async def test_lambda_rlm_flag_on_skips_decompose_and_rlm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    transport = _SynthOnlyTransport()
    bundle = ResolvedCdOuterModels(
        outer_model_id="m",
        outer_transport=transport,
        outer_budget=ModelBudget(model_id="m", regime=BudgetRegime.FREE_LOCAL),
        sub_lm_model_id=None,
        sub_lm_transport=None,
        sub_lm_budget=None,
    )
    exe, ts = _minimal_tooling()
    calls: list[int] = []

    def _fake_interpreter(_ws: object) -> object:
        calls.append(1)
        return object()

    monkeypatch.setattr(
        "sevn.agent.executors.cd_harness.build_rlm_interpreter",
        _fake_interpreter,
    )
    outcome = await run_cd_turn(
        workspace=_make_workspace(tmp=tmp_path, allowlist=["tick"]),
        session=SessionHandle(session_id="s1"),
        turn_id="t1",
        triage=_triage_c(),
        incoming_text="lambda task",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        transport_outer=bundle,
        trace=None,
        steer_buffer=None,
        plan_gate=NoOpPlanGate(),
        tool_executor=exe,
        tool_context=ToolContext(
            session_id="s1",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t1",
        ),
    )

    assert outcome.status == "completed"
    assert outcome.c_d_backend == "lambda_rlm"
    assert transport.phases == ["synthesize"]
    assert calls == []
    assert outcome.rounds_outer_used == 1


@pytest.mark.asyncio
async def test_lambda_rlm_trace_attrs_and_degraded_span(tmp_path: Path) -> None:
    events: list[TraceEvent] = []

    class _Sink(TraceSink):
        async def emit(self, event: TraceEvent) -> None:
            events.append(event)

        async def flush(self) -> None:
            return None

        async def close(self) -> None:
            return None

    transport = _SynthOnlyTransport()
    bundle = ResolvedCdOuterModels(
        outer_model_id="m",
        outer_transport=transport,
        outer_budget=ModelBudget(model_id="m", regime=BudgetRegime.FREE_LOCAL),
        sub_lm_model_id=None,
        sub_lm_transport=None,
        sub_lm_budget=None,
    )
    exe, ts = _minimal_tooling()
    await run_cd_turn(
        workspace=_make_workspace(tmp=tmp_path, allowlist=["tick", "ghost"]),
        session=SessionHandle(session_id="s"),
        turn_id="t",
        triage=_triage_c(),
        incoming_text="x",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=4),
        transport_outer=bundle,
        trace=_Sink(),
        steer_buffer=None,
        plan_gate=NoOpPlanGate(),
        tool_executor=exe,
        tool_context=ToolContext(
            session_id="s",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t",
        ),
    )
    started = [e for e in events if e.kind == "cd.turn" and e.status == "started"]
    assert started
    assert started[0].attrs.get("c_d.backend") == "lambda_rlm"
    assert started[0].attrs.get("c_d.leaf_allowed_count") == 1
    degraded = [e for e in events if e.kind == "cd.lambda.degraded"]
    assert degraded
    assert degraded[0].attrs.get("message") == LAMBDA_RLM_DEGRADED_PLAN_SPLIT_MESSAGE
