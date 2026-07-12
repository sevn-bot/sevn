"""Identity smoke: persona in wire payload, no vendor leak (recovery Wave A)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sevn.agent.executors import b_harness as b_harness_mod
from sevn.agent.executors.b_harness import run_b_turn
from sevn.agent.executors.b_types import ResolvedTierBModel, SessionHandle
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.config.workspace_config import SecurityWorkspaceConfig, WorkspaceConfig
from sevn.tools.base import FunctionTool, ToolDefinition, ToolExecutor, enveloped_success
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.meta_loaders import attach_meta_loaders
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import ToolSet, merge_skill_manifests, snapshot_tool_set

_PROVIDER_BRANDS = ("MiniMax", "Claude", "GPT", "Anthropic", "OpenAI")


def _openai_assistant_text(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class _ScriptedChatTransport(ChatCompletionsTransport):
    def __init__(self, fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> None:
        super().__init__(proxy_base_url="http://identity-smoke.test.invalid")
        self._fn = fn

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        return await self._fn(dict(request))


def _make_registry() -> tuple[ToolExecutor, ToolSet]:
    exe = ToolExecutor(default_timeout_seconds=30.0)

    async def _tick(_ctx: ToolContext) -> str:
        return enveloped_success({"tick": True})

    tick_def = ToolDefinition(
        name="tick",
        category="meta",
        description="Deterministic harness tick.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    )
    exe.register(FunctionTool(tick_def, _tick))
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
        registry_version=77,
        skill_descriptions=merged,
        skill_inventory={},
        mcp_definitions=(),
        mcp_names=frozenset(),
    )
    return exe, ts


@pytest.mark.asyncio
async def test_tier_b_outbound_echo_contains_sevn_not_vendors(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "IDENTITY.md").write_text(
        "Name: Sevn\nRole: Personal AI assistant for sevn.bot.",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}
    original_agent = b_harness_mod.Agent

    class _CaptureAgent(original_agent):
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured.update(kwargs)
            super().__init__(*args, **kwargs)

    exe, tool_set = _make_registry()
    triage = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )

    async def _reply(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text("I am Sevn, your workspace assistant.")

    transport = _ScriptedChatTransport(_reply)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    with patch.object(b_harness_mod, "Agent", _CaptureAgent):
        outcome = await run_b_turn(
            workspace=WorkspaceConfig(
                schema_version=1,
                workspace_root=str(root),
                security=SecurityWorkspaceConfig(),
                gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
            ),
            session=SessionHandle(session_id="s-smoke"),
            turn_id="t-smoke",
            triage=triage,
            incoming_text="who are you?",
            tool_set=tool_set,
            body_cache=LoadedBodyCache(capacity=8),
            tool_executor=exe,
            transport_bundle=bundle,
            trace=None,
            steer_buffer=None,
            tool_context=ToolContext(
                session_id="s-smoke",
                workspace_path=root,
                workspace_id="w",
                registry_version=tool_set.registry_version,
                trace=None,
                permissions=AllowAllPermissionPolicy(),
                turn_id="t-smoke",
            ),
        )
    system_prompt = str(captured.get("system_prompt", ""))
    assert "sevn" in system_prompt.lower()
    assert outcome.status == "completed"
    assert outcome.final_messages
    outbound = outcome.final_messages[-1].text or ""
    lowered = outbound.lower()
    assert "sevn" in lowered
    for brand in _PROVIDER_BRANDS:
        assert brand.lower() not in lowered
