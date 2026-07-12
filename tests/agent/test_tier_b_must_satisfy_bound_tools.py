"""W2 — must-satisfy bound tools + zero-tool completion reclassify (msg=f26e32, bc75f9)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.executors.b_harness import _triager_bound_registry_tools, run_b_turn
from sevn.agent.executors.b_types import ResolvedTierBModel, SessionHandle, SteerInject
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.config.workspace_config import SecurityWorkspaceConfig, WorkspaceConfig
from sevn.tools.base import FunctionTool, ToolDefinition, ToolExecutor, enveloped_success
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.meta_loaders import attach_meta_loaders
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import merge_skill_manifests, snapshot_tool_set


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
        super().__init__(proxy_base_url="http://tier-b-must-satisfy.test.invalid")
        self._fn = fn
        self.requests: list[dict[str, Any]] = []

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        body = dict(request)
        self.requests.append(body)
        return await self._fn(body)


def _make_search_in_file_executor() -> tuple[ToolExecutor, Any]:
    exe = ToolExecutor(default_timeout_seconds=30.0)

    async def _search(_ctx: ToolContext, **kwargs: Any) -> str:
        _ = kwargs
        return enveloped_success({"matches": [{"line": "temperature: 72"}]})

    search_def = ToolDefinition(
        name="search_in_file",
        category="file_ops",
        description="Search file contents.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["pattern", "path"],
        },
    )
    exe.register(FunctionTool(search_def, _search))

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
        registry_version=88,
        skill_descriptions=merged,
        skill_inventory={},
        mcp_definitions=(),
        mcp_names=frozenset(),
    )
    return exe, ts


def _triage(*, tools: list[str]) -> TriageResult:
    return TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it — searching the workspace.",
        tools=tools,
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )


def _workspace(tmp: Path) -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        workspace_root=str(tmp),
        security=SecurityWorkspaceConfig(),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


def test_triager_bound_registry_tools_excludes_meta_only() -> None:
    """W2.1: meta loaders are not must-satisfy registry picks."""
    assert _triager_bound_registry_tools(["search_in_file", "load_tool"]) == frozenset(
        {"search_in_file"},
    )
    assert _triager_bound_registry_tools(["load_tool", "list_registry"]) == frozenset()


@pytest.mark.asyncio
async def test_bc75f9_zero_tool_narrative_audit_fails_not_completed(tmp_path: Path) -> None:
    """msg=bc75f9: bound ``search_in_file``, zero successful tools → failed (not completed)."""
    exe, ts = _make_search_in_file_executor()
    triage = _triage(tools=["search_in_file"])
    steer = SteerInject()
    audit_narrative = (
        "Tool audit summary:\n"
        "| Tool | Attempted | Result |\n"
        "| search_in_file | no | load_tool never dispatched |\n"
        "Conclusion: search_in_file could not be used this turn."
    )

    async def _fabricated_audit(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text(audit_narrative)

    transport = _ScriptedChatTransport(_fabricated_audit)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s-bc75f9"),
        turn_id="t-bc75f9",
        triage=triage,
        incoming_text="audit which tools were called for temperature search",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=steer,
        tool_context=ToolContext(
            session_id="s-bc75f9",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-bc75f9",
        ),
        max_rounds=4,
    )
    assert outcome.status == "failed"
    assert outcome.final_messages == ()
    assert outcome.failure_detail == "triager_bound_tools_unused"
    assert "search_in_file" not in outcome.successful_tools_called
    assert steer.pop_pending() is not None


@pytest.mark.asyncio
async def test_bound_search_in_file_success_still_completes(tmp_path: Path) -> None:
    """W2.5: successful bound ``search_in_file`` must not false-positive the W2 guard."""
    exe, ts = _make_search_in_file_executor()
    triage = _triage(tools=["search_in_file"])
    steer = SteerInject()
    step = 0

    async def _search_then_answer(_req: dict[str, Any]) -> dict[str, Any]:
        nonlocal step
        step += 1
        if step == 1:
            return _openai_assistant_tool(
                "search_in_file",
                json.dumps({"pattern": "temperature", "path": "."}),
                call_id="c-search",
            )
        return _openai_assistant_text("Found temperature mentions in notes.md.")

    transport = _ScriptedChatTransport(_search_then_answer)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s-w2-ok"),
        turn_id="t-w2-ok",
        triage=triage,
        incoming_text="search markdown for temperature",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=steer,
        tool_context=ToolContext(
            session_id="s-w2-ok",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-w2-ok",
        ),
        max_rounds=4,
    )
    assert outcome.status == "completed"
    assert "search_in_file" in outcome.successful_tools_called
    assert any("temperature" in m.text for m in outcome.final_messages)
    assert steer.pop_pending() is None
