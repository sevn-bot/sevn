"""W8.2 - tier-B must not infinite-retry after successful ``load_skill`` (#126, W11)."""

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
from sevn.config.workspace_config import SecurityWorkspaceConfig, WorkspaceConfig
from sevn.gateway.agent_turn import (
    _is_deterministic_harness_failure,
    _tier_b_full_index_retry_warranted,
)
from sevn.skills.manager import SkillsManager
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry
from sevn.workspace.layout import WorkspaceLayout

_FIXTURE_SKILL = Path(__file__).resolve().parents[1] / "fixtures" / "skills" / "min_echo"
_MAX_PROVIDER_CALLS_AFTER_LOAD_SKILL = 12


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


def _openai_assistant_empty() -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": ""}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 0},
    }


class _ScriptedChatTransport(ChatCompletionsTransport):
    def __init__(self, fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> None:
        super().__init__(proxy_base_url="http://tier-b-output-retry.test.invalid")
        self._fn = fn
        self.requests: list[dict[str, Any]] = []

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        body = dict(request)
        self.requests.append(body)
        return await self._fn(body)

    async def complete_stream(self, request: dict[str, object]) -> Any:
        from sevn.agent.providers.transport import StreamFinal, StreamTextDelta

        payload = await self.complete(request)
        choices = payload.get("choices") or [{}]
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        content = message.get("content")
        if isinstance(content, str) and content:
            for ch in content:
                yield StreamTextDelta(text=ch)
        yield StreamFinal(response=payload)


@pytest.fixture(autouse=True)
def _reset_skill_singletons() -> None:
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


def _seed_min_echo_workspace(workspace: Path) -> None:
    (workspace / "skills" / "user").mkdir(parents=True, exist_ok=True)
    shutil.copytree(_FIXTURE_SKILL, workspace / "skills" / "user" / "min_echo")


def _workspace_cfg(workspace: Path) -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        workspace_root=str(workspace),
        security=SecurityWorkspaceConfig(),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


async def _run_load_skill_scenario(
    tmp_path: Path,
    *,
    after_load_plan: list[dict[str, Any]],
) -> tuple[Any, _ScriptedChatTransport]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _seed_min_echo_workspace(workspace)
    ws = _workspace_cfg(workspace)
    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    executor, tool_set = build_session_registry(
        workspace_root=workspace,
        layout=layout,
        workspace_config=ws,
        trace_sink=None,
    )
    triage = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="loading skill",
        tools=["load_skill", "run_skill_script"],
        skills=["min_echo"],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    plan = iter(
        [
            _openai_assistant_tool("load_skill", '{"name":"min_echo"}', call_id="c1"),
            *after_load_plan,
        ],
    )

    async def _seq(_req: dict[str, Any]) -> dict[str, Any]:
        return next(plan)

    transport = _ScriptedChatTransport(_seq)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-output-retry",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-output-retry", regime=BudgetRegime.FREE_LOCAL),
    )
    outcome = await run_b_turn(
        workspace=ws,
        session=SessionHandle(session_id="output-retry-sess"),
        turn_id="output-retry-turn",
        triage=triage,
        incoming_text="use min_echo skill",
        tool_set=tool_set,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=executor,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=ToolContext(
            session_id="output-retry-sess",
            workspace_path=workspace,
            workspace_id="output-retry-ws",
            registry_version=tool_set.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="output-retry-turn",
        ),
    )
    return outcome, transport


@pytest.mark.asyncio
async def test_tier_b_completes_after_successful_load_skill_when_model_recovers(
    tmp_path: Path,
) -> None:
    """Successful ``load_skill`` then one empty body must not abort the turn before a real answer."""
    outcome, transport = await _run_load_skill_scenario(
        tmp_path,
        after_load_plan=[
            _openai_assistant_empty(),
            _openai_assistant_text("Skill loaded; echo ready."),
        ],
    )
    assert "load_skill" in outcome.successful_tools_called
    assert outcome.status == "completed"
    joined = " ".join(m.text for m in outcome.final_messages)
    assert "echo ready" in joined.lower()
    assert len(transport.requests) <= _MAX_PROVIDER_CALLS_AFTER_LOAD_SKILL


@pytest.mark.asyncio
async def test_tier_b_post_load_skill_empty_output_is_bounded(tmp_path: Path) -> None:
    """After ``load_skill`` succeeds, empty assistant bodies must not storm the provider."""
    empty_plan = [_openai_assistant_empty() for _ in range(6)]
    outcome, transport = await _run_load_skill_scenario(tmp_path, after_load_plan=empty_plan)
    assert "load_skill" in outcome.successful_tools_called
    assert len(transport.requests) <= _MAX_PROVIDER_CALLS_AFTER_LOAD_SKILL


@pytest.mark.asyncio
async def test_tier_b_post_load_skill_failure_summary_is_not_raw_output_retries(
    tmp_path: Path,
) -> None:
    """When tier-B fails after ``load_skill``, surface skill context — not bare retry boilerplate."""
    outcome, _transport = await _run_load_skill_scenario(
        tmp_path,
        after_load_plan=[_openai_assistant_empty() for _ in range(6)],
    )
    assert "load_skill" in outcome.successful_tools_called
    detail = str(getattr(outcome, "failure_detail", "") or "")
    joined = " ".join(m.text for m in outcome.final_messages)
    blob = f"{detail} {joined}".lower()
    if "maximum output retries" in blob:
        assert "min_echo" in blob or "load_skill" in blob or "skill" in blob
    else:
        assert outcome.status == "completed"
        assert joined.strip()


def test_output_retry_after_load_skill_skips_full_index_retry() -> None:
    """Gateway must treat post-``load_skill`` output-retry faults as deterministic (no widen loop)."""
    from types import SimpleNamespace

    outcome = SimpleNamespace(
        status="failed",
        final_messages=(),
        had_tool_failures=False,
        successful_skills_called=frozenset({"social_media_manager"}),
        failure_detail="Exceeded maximum output retries (3)",
    )
    assert _is_deterministic_harness_failure(no_answer_reason=None, outcome=outcome) is True
    assert _tier_b_full_index_retry_warranted(no_answer_reason=None, outcome=outcome) is False
