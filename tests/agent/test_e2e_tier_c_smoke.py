"""Tier-C E2E smoke gate (`plan/improve/v1-smoke-tier-cd-gate-wave-plan.md`; `specs/21` §10.4).

Synthetic channel text → Triager (stub) → tier-C ``run_cd_turn`` → user-visible reply.
Runs under default ``make test`` (no ``integration`` marker).
"""

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
from sevn.agent.triager.context import (
    ApprovedUserTurn,
    RegistrySnapshot,
    SessionView,
    TriagePromptContext,
)
from sevn.agent.triager.models import ComplexityTier, Intent
from sevn.agent.triager.run import triage_turn
from sevn.config.workspace_config import WorkspaceConfig, parse_workspace_config
from sevn.tools.base import FunctionTool, ToolDefinition, ToolExecutor, enveloped_success
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import ToolSet, merge_skill_manifests, snapshot_tool_set

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "triager"
_TIER_C_STUB = _FIXTURE_DIR / "tier_c_stub.json"


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
        super().__init__(proxy_base_url="http://tier-cd-e2e-smoke.test.invalid")

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        raw = request["messages"]
        assert isinstance(raw, list)
        assert raw
        body = json.loads(str(raw[0].get("content", "")))
        phase = str(body.get("__sevn_cd_phase", ""))
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
            return _assistant_json({"final_text": "All set."})
        return _assistant_json({})


def _make_workspace(tmp: Path) -> WorkspaceConfig:
    return parse_workspace_config(
        {
            "schema_version": 1,
            "workspace_root": str(tmp),
            "security": {},
            "rlm": {"c_d_backend": "dspy"},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
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
async def test_e2e_tier_c_smoke_triager_to_cd_reply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Synthetic inbound text → triage → tier-C DSPy path → coherent assistant text."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_TIER_C_STUB))

    registry = RegistrySnapshot(registry_version=1, tools=[])
    triage_ws = WorkspaceConfig.minimal(
        triager={"group_scope": "all", "relax_greeting_lists": False},
        providers={"tier_default": {"triager": "stub/model"}},
        permissions={"scope_narrowing": {"enabled": False}},
    )
    incoming_text = "plan a multi-step rollout for the new feature"

    triage = await triage_turn(
        workspace=triage_ws,
        session=SessionView(session_id="e2e-c-sess"),
        incoming=ApprovedUserTurn(text=incoming_text),
        registry_snapshot=registry,
        triage_context=TriagePromptContext(current_message=incoming_text),
    )
    assert triage.complexity == ComplexityTier.C
    assert triage.intent == Intent.NEW_REQUEST

    transport = _PhaseRecordingTransport()
    bundle = ResolvedCdOuterModels(
        outer_model_id="openai/gpt-e2e-c",
        outer_transport=transport,
        outer_budget=ModelBudget(model_id="openai/gpt-e2e-c", regime=BudgetRegime.FREE_LOCAL),
        sub_lm_model_id="openai/sub",
        sub_lm_transport=transport,
        sub_lm_budget=ModelBudget(model_id="openai/sub", regime=BudgetRegime.FREE_LOCAL),
    )
    exe, tool_set = _minimal_tooling()

    def _fake_interpreter(_ws: object) -> object:
        return object()

    monkeypatch.setattr(
        "sevn.agent.executors.cd_harness.build_rlm_interpreter",
        _fake_interpreter,
    )
    workspace = _make_workspace(tmp_path)
    outcome = await run_cd_turn(
        workspace=workspace,
        session=SessionHandle(session_id="e2e-c-sess"),
        turn_id="e2e-c-turn-1",
        triage=triage,
        incoming_text=incoming_text,
        tool_set=tool_set,
        body_cache=LoadedBodyCache(capacity=8),
        transport_outer=bundle,
        trace=None,
        steer_buffer=None,
        plan_gate=NoOpPlanGate(),
        tool_executor=exe,
        tool_context=ToolContext(
            session_id="e2e-c-sess",
            workspace_path=tmp_path,
            workspace_id="e2e-c-ws",
            registry_version=tool_set.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="e2e-c-turn-1",
        ),
    )
    assert outcome.status == "completed"
    assert outcome.c_d_backend == "dspy"
    joined = " ".join(m.text for m in outcome.final_messages)
    assert joined.strip()
    assert "All set." in joined
