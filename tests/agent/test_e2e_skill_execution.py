"""Tier-B agent-loop E2E: load_skill → run_skill_script (`plan/tools-skills-e2e-wave-plan.md` Wave 4)."""

from __future__ import annotations

import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.executors.b_harness import run_b_turn
from sevn.agent.executors.b_types import ResolvedTierBModel, SessionHandle
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.config.workspace_config import (
    SecurityWorkspaceConfig,
    WorkspaceConfig,
    parse_workspace_config,
)
from sevn.skills.manager import SkillsManager
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry
from sevn.workspace.layout import WorkspaceLayout

_FIXTURE_SKILL = Path(__file__).resolve().parents[1] / "fixtures" / "skills" / "min_echo"


def _openai_assistant_tool(name: str, arguments: str, *, call_id: str = "call-1") -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        },
                    ],
                },
            },
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def _openai_assistant_text(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class _ScriptedChatTransport(ChatCompletionsTransport):
    def __init__(self, fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> None:
        super().__init__(proxy_base_url="http://e2e-skill-execution.test.invalid")
        self._fn = fn

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        return await self._fn(dict(request))


class _RecordingTrace:
    """Minimal ``TraceSink`` capturing ``emit`` calls for assertions."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return None

    async def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_skill_singletons() -> None:
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


def _seed_min_echo_workspace(workspace: Path) -> None:
    (workspace / "skills" / "user").mkdir(parents=True, exist_ok=True)
    shutil.copytree(_FIXTURE_SKILL, workspace / "skills" / "user" / "min_echo")


@pytest.mark.asyncio
async def test_e2e_skill_load_then_run_script(tmp_path: Path) -> None:
    """``build_session_registry`` + tier-B harness: load_skill → run_skill_script → reply."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _seed_min_echo_workspace(workspace)
    ws = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    trace = _RecordingTrace()
    executor, tool_set = build_session_registry(
        workspace_root=workspace,
        layout=layout,
        workspace_config=ws,
        trace_sink=trace,
    )
    assert "min_echo" in tool_set.skill_descriptions

    triage = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="running min_echo",
        tools=["run_skill_script"],
        skills=["min_echo"],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )

    plan = iter(
        [
            _openai_assistant_tool("load_skill", '{"name":"min_echo"}', call_id="c1"),
            _openai_assistant_tool(
                "run_skill_script",
                '{"skill":"min_echo","script":"scripts/echo.py","argv":["hi"]}',
                call_id="c2",
            ),
            _openai_assistant_text("Echo result: hi"),
        ],
    )

    async def _seq(_req: dict[str, Any]) -> dict[str, Any]:
        return next(plan)

    transport = _ScriptedChatTransport(_seq)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-e2e-skill",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-e2e-skill", regime=BudgetRegime.FREE_LOCAL),
    )
    workspace_cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=str(workspace),
        security=SecurityWorkspaceConfig(),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    outcome = await run_b_turn(
        workspace=workspace_cfg,
        session=SessionHandle(session_id="e2e-skill-sess"),
        turn_id="e2e-skill-turn",
        triage=triage,
        incoming_text="echo hi via min_echo skill",
        tool_set=tool_set,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=executor,
        transport_bundle=bundle,
        trace=trace,
        steer_buffer=None,
        tool_context=ToolContext(
            session_id="e2e-skill-sess",
            workspace_path=workspace,
            workspace_id="e2e-skill-ws",
            registry_version=tool_set.registry_version,
            trace=trace,
            permissions=AllowAllPermissionPolicy(),
            turn_id="e2e-skill-turn",
        ),
    )

    assert outcome.status == "completed"
    joined = " ".join(m.text for m in outcome.final_messages)
    assert "Echo result: hi" in joined

    trace_kinds = [getattr(e, "kind", None) for e in trace.events]
    assert "skill.load" in trace_kinds
    assert "skill.run" in trace_kinds
