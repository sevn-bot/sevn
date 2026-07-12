"""Tier C/D DSPy default path (`specs/21-executor-tier-cd.md` §4.1; Wave 8 gate)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.executors.b_types import SessionHandle
from sevn.agent.executors.cd_harness import NoOpPlanGate, SupersedingPlanGate, run_cd_turn
from sevn.agent.executors.cd_types import ResolvedCdOuterModels
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.config.defaults import CD_SYNTH_MAX_CHARS
from sevn.config.workspace_config import parse_workspace_config
from sevn.tools.base import FunctionTool, ToolDefinition, ToolExecutor, enveloped_success
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import ToolSet, merge_skill_manifests, snapshot_tool_set


def _plan_json(*, complexity: str = "C") -> dict[str, Any]:
    return {
        "steps": [
            {
                "id": "1",
                "title": "step one",
                "tool_guess": None,
                "requires_human": False,
            }
        ],
        "summary": "exec summary",
        "meta": {"complexity": complexity, "registry_version": 1},
    }


def _assistant_json(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": json.dumps(obj)}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class _PhaseRecordingTransport(ChatCompletionsTransport):
    def __init__(self) -> None:
        super().__init__(proxy_base_url="http://tier-cd-dspy.test.invalid")
        self.phases: list[str] = []
        self.synth_payloads: list[dict[str, Any]] = []

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        raw = request["messages"]
        assert isinstance(raw, list)
        assert raw
        body = json.loads(str(raw[0].get("content", "")))
        phase = str(body.get("__sevn_cd_phase", ""))
        self.phases.append(phase)
        if phase == "decompose":
            return _assistant_json(_plan_json())
        if phase == "rlm_outer":
            return _assistant_json(
                {
                    "result": "rlm-done",
                    "continue_outer": False,
                    "inner_llm_calls": 2,
                    "inner_exhausted": False,
                },
            )
        if phase == "synthesize":
            self.synth_payloads.append(body)
            return _assistant_json({"final_text": "All set."})
        return _assistant_json({})


def _make_workspace(
    *,
    tmp: Path,
    backend: str = "dspy",
    lambda_enabled: bool = False,
) -> object:
    rlm: dict[str, Any] = {"c_d_backend": backend}
    data: dict[str, Any] = {
        "schema_version": 1,
        "workspace_root": str(tmp),
        "security": {},
        "rlm": rlm,
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    if lambda_enabled:
        data["executors"] = {"tier_cd": {"lambda_rlm": {"enabled": True}}}
    return parse_workspace_config(data)


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
async def test_dspy_default_phase_ordering_decompose_gate_rlm_synth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    transport = _PhaseRecordingTransport()
    bundle = ResolvedCdOuterModels(
        outer_model_id="openai/gpt-test",
        outer_transport=transport,
        outer_budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
        sub_lm_model_id="openai/sub",
        sub_lm_transport=transport,
        sub_lm_budget=ModelBudget(model_id="openai/sub", regime=BudgetRegime.FREE_LOCAL),
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
        workspace=_make_workspace(tmp=tmp_path),
        session=SessionHandle(session_id="s1"),
        turn_id="t1",
        triage=_triage_c(),
        incoming_text="hello",
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
    assert outcome.c_d_backend == "dspy"
    assert transport.phases == ["decompose", "rlm_outer", "synthesize"]
    assert calls == [1]


@pytest.mark.asyncio
async def test_dspy_plan_gate_superseded_skips_execute(tmp_path: Path) -> None:
    transport = _PhaseRecordingTransport()
    bundle = ResolvedCdOuterModels(
        outer_model_id="m",
        outer_transport=transport,
        outer_budget=ModelBudget(model_id="m", regime=BudgetRegime.FREE_LOCAL),
        sub_lm_model_id="m",
        sub_lm_transport=transport,
        sub_lm_budget=ModelBudget(model_id="m", regime=BudgetRegime.FREE_LOCAL),
    )
    exe, ts = _minimal_tooling()
    outcome = await run_cd_turn(
        workspace=_make_workspace(tmp=tmp_path),
        session=SessionHandle(session_id="s1"),
        turn_id="t1",
        triage=_triage_c(),
        incoming_text="hello",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        transport_outer=bundle,
        trace=None,
        steer_buffer=None,
        plan_gate=SupersedingPlanGate(),
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
    assert outcome.status == "superseded"
    assert transport.phases == ["decompose"]


@pytest.mark.asyncio
async def test_dspy_outer_round_budget_counter(tmp_path: Path) -> None:
    class _MultiOuter(_PhaseRecordingTransport):
        async def complete(self, request: dict[str, object]) -> dict[str, object]:
            raw = request["messages"]
            assert isinstance(raw, list)
            assert raw
            body = json.loads(str(raw[0].get("content", "")))
            phase = str(body.get("__sevn_cd_phase", ""))
            self.phases.append(phase)
            if phase == "decompose":
                return _assistant_json(_plan_json())
            if phase == "rlm_outer":
                idx = body.get("outer_index", 0)
                if int(idx) < 2:
                    return _assistant_json(
                        {
                            "result": f"o{idx}",
                            "continue_outer": True,
                            "inner_llm_calls": 1,
                            "inner_exhausted": False,
                        },
                    )
                return _assistant_json(
                    {
                        "result": "last",
                        "continue_outer": False,
                        "inner_llm_calls": 3,
                        "inner_exhausted": True,
                    },
                )
            if phase == "synthesize":
                return _assistant_json({"final_text": "ok"})
            return _assistant_json({})

    transport = _MultiOuter()
    bundle = ResolvedCdOuterModels(
        outer_model_id="m",
        outer_transport=transport,
        outer_budget=ModelBudget(model_id="m", regime=BudgetRegime.FREE_LOCAL),
        sub_lm_model_id="s",
        sub_lm_transport=transport,
        sub_lm_budget=ModelBudget(model_id="s", regime=BudgetRegime.FREE_LOCAL),
    )
    exe, ts = _minimal_tooling()
    outcome = await run_cd_turn(
        workspace=_make_workspace(tmp=tmp_path),
        session=SessionHandle(session_id="s"),
        turn_id="t",
        triage=_triage_c(),
        incoming_text="hi",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=4),
        transport_outer=bundle,
        trace=None,
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
    assert outcome.rounds_outer_used == 3
    assert outcome.rounds_inner_exhausted is True
    assert transport.phases.count("rlm_outer") == 3


@pytest.mark.asyncio
async def test_synth_payload_truncates_execute_blob(tmp_path: Path) -> None:
    transport = _PhaseRecordingTransport()

    class _HugeRlm(_PhaseRecordingTransport):
        async def complete(self, request: dict[str, object]) -> dict[str, object]:
            raw = request["messages"]
            assert isinstance(raw, list)
            body = json.loads(str(raw[0].get("content", "")))
            phase = str(body.get("__sevn_cd_phase", ""))
            self.phases.append(phase)
            if phase == "decompose":
                return _assistant_json(_plan_json())
            if phase == "rlm_outer":
                return _assistant_json(
                    {
                        "result": "x" * (CD_SYNTH_MAX_CHARS + 500),
                        "continue_outer": False,
                        "inner_llm_calls": 0,
                        "inner_exhausted": False,
                    },
                )
            if phase == "synthesize":
                self.synth_payloads.append(body)
                return _assistant_json({"final_text": "ok"})
            return _assistant_json({})

    transport = _HugeRlm()
    bundle = ResolvedCdOuterModels(
        outer_model_id="m",
        outer_transport=transport,
        outer_budget=ModelBudget(model_id="m", regime=BudgetRegime.FREE_LOCAL),
        sub_lm_model_id="m",
        sub_lm_transport=transport,
        sub_lm_budget=ModelBudget(model_id="m", regime=BudgetRegime.FREE_LOCAL),
    )
    exe, ts = _minimal_tooling()
    await run_cd_turn(
        workspace=_make_workspace(tmp=tmp_path),
        session=SessionHandle(session_id="s"),
        turn_id="t",
        triage=_triage_c(),
        incoming_text="hi",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=4),
        transport_outer=bundle,
        trace=None,
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
    assert transport.synth_payloads
    result = str(transport.synth_payloads[0].get("result", ""))
    assert len(result) <= CD_SYNTH_MAX_CHARS


@pytest.mark.asyncio
async def test_lambda_rlm_config_without_flag_stays_dspy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``rlm.c_d_backend=lambda_rlm`` is ignored when ``executors.tier_cd.lambda_rlm.enabled`` is false."""

    transport = _PhaseRecordingTransport()
    bundle = ResolvedCdOuterModels(
        outer_model_id="m",
        outer_transport=transport,
        outer_budget=ModelBudget(model_id="m", regime=BudgetRegime.FREE_LOCAL),
        sub_lm_model_id="m",
        sub_lm_transport=transport,
        sub_lm_budget=ModelBudget(model_id="m", regime=BudgetRegime.FREE_LOCAL),
    )
    exe, ts = _minimal_tooling()
    monkeypatch.setattr(
        "sevn.agent.executors.cd_harness.build_rlm_interpreter",
        lambda _ws: object(),
    )
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "workspace_root": str(tmp_path),
            "security": {},
            "rlm": {"c_d_backend": "lambda_rlm", "lambda_tool_allowlist": ["tick"]},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    outcome = await run_cd_turn(
        workspace=ws,
        session=SessionHandle(session_id="s"),
        turn_id="t",
        triage=_triage_c(),
        incoming_text="hi",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=4),
        transport_outer=bundle,
        trace=None,
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
    assert outcome.c_d_backend == "dspy"
    assert "decompose" in transport.phases
