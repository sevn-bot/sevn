"""Tier-B agent-loop E2E: read → edit → search_in_file (`plan/tools-skills-full-inventory-wave-plan.md` Wave Z)."""

from __future__ import annotations

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
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry
from sevn.workspace.layout import WorkspaceLayout


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
        super().__init__(proxy_base_url="http://e2e-file-ops.test.invalid")
        self._fn = fn

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        return await self._fn(dict(request))


@pytest.mark.asyncio
async def test_e2e_file_ops_read_edit_search(tmp_path: Path) -> None:
    """``build_session_registry`` + tier-B harness: read → edit → search_in_file → reply."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("alpha line\nbeta line\n", encoding="utf-8")

    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    executor, tool_set = build_session_registry(
        workspace_root=workspace,
        layout=layout,
        registry_version=1,
    )
    names = {definition.name for definition in executor.definitions()}
    assert {"read", "edit", "search_in_file"} <= names

    triage = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="edit notes",
        tools=["read", "edit", "search_in_file"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )

    plan = iter(
        [
            _openai_assistant_tool("load_tool", '{"name":"read"}', call_id="c0"),
            _openai_assistant_tool(
                "read",
                '{"path":"notes.txt"}',
                call_id="c1",
            ),
            _openai_assistant_tool("load_tool", '{"name":"edit"}', call_id="c2"),
            _openai_assistant_tool(
                "edit",
                '{"path":"notes.txt","old_string":"alpha line","new_string":"ALPHA line"}',
                call_id="c3",
            ),
            _openai_assistant_tool("load_tool", '{"name":"search_in_file"}', call_id="c4"),
            _openai_assistant_tool(
                "search_in_file",
                '{"pattern":"ALPHA","path":"."}',
                call_id="c5",
            ),
            _openai_assistant_text("Updated notes.txt and confirmed ALPHA via search."),
        ],
    )

    async def _seq(_req: dict[str, Any]) -> dict[str, Any]:
        return next(plan)

    transport = _ScriptedChatTransport(_seq)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-e2e-file-ops",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-e2e-file-ops", regime=BudgetRegime.FREE_LOCAL),
    )
    workspace_cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=str(workspace),
        security=SecurityWorkspaceConfig(),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    outcome = await run_b_turn(
        workspace=workspace_cfg,
        session=SessionHandle(session_id="e2e-file-ops-sess"),
        turn_id="e2e-file-ops-turn",
        triage=triage,
        incoming_text="read notes.txt, rename alpha to ALPHA, then search for ALPHA",
        tool_set=tool_set,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=executor,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=ToolContext(
            session_id="e2e-file-ops-sess",
            workspace_path=workspace,
            workspace_id="e2e-file-ops-ws",
            registry_version=tool_set.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="e2e-file-ops-turn",
        ),
    )

    assert outcome.status == "completed"
    joined = " ".join(m.text for m in outcome.final_messages)
    assert "ALPHA" in joined
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "ALPHA line\nbeta line\n"
