"""Single-message agent E2E gate (`plan/v1-tasks-ordered.md` Wave 5).

Synthetic channel text → Triager (stub) → tier-B executor → user-visible reply.
Runs under default ``make test`` (no ``integration`` marker).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.executors.b_harness import run_b_turn
from sevn.agent.executors.b_types import ResolvedTierBModel, SessionHandle
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.triager.context import (
    ApprovedUserTurn,
    RegistryIndexEntry,
    RegistrySnapshot,
    SessionView,
    TriagePromptContext,
)
from sevn.agent.triager.models import ComplexityTier, Intent
from sevn.agent.triager.run import triage_turn
from sevn.config.workspace_config import (
    SecurityWorkspaceConfig,
    WorkspaceConfig,
    parse_workspace_config,
)
from sevn.tools.base import FunctionTool, ToolDefinition, ToolExecutor, enveloped_success
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.meta_loaders import attach_meta_loaders
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import merge_skill_manifests, snapshot_tool_set

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "triager"
_GOLDEN_ROUTING = _FIXTURE_DIR / "golden_routing.jsonl"
_E2E_STUB = _FIXTURE_DIR / "e2e_tier_b_stub.json"


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
        super().__init__(proxy_base_url="http://e2e-single-message.test.invalid")
        self._fn = fn

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        return await self._fn(dict(request))


def _tick_executor() -> tuple[ToolExecutor, Any]:
    exe = ToolExecutor(default_timeout_seconds=30.0)

    async def _tick(_ctx: ToolContext) -> str:
        return enveloped_success({"tick": True})

    tick_def = ToolDefinition(
        name="tick",
        category="meta",
        description="E2E harness tick.",
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
        registry_version=1,
        skill_descriptions=merged,
        skill_inventory={},
        mcp_definitions=(),
        mcp_names=frozenset(),
    )
    return exe, ts


def test_golden_routing_fixture_has_minimum_rows() -> None:
    """``golden_routing.jsonl`` ships ≥200 labelled rows (Wave 5)."""
    lines = [ln for ln in _GOLDEN_ROUTING.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 200
    sample = json.loads(lines[0])
    assert "message" in sample
    assert "labels" in sample


@pytest.mark.parametrize("line_no", range(12))
def test_golden_routing_labels_validate_against_triage_result(line_no: int) -> None:
    """Each golden row's labels are structurally compatible with ``TriageResult``."""
    from sevn.agent.triager.models import TriageResult

    lines = _GOLDEN_ROUTING.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[line_no])
    labels = row["labels"]
    payload = {
        "intent": labels["intent"],
        "complexity": labels["complexity"],
        "first_message": "fixture",
        "tools": labels.get("tools", []),
        "skills": labels.get("skills", []),
        "mcp_servers_required": labels.get("mcp_servers_required", []),
        "confidence": 0.5,
        "requires_vision": False,
        "requires_document": False,
        "disregard": labels.get("disregard", False),
    }
    if labels["intent"] == "GREETING":
        payload["tools"] = []
        payload["skills"] = []
    TriageResult.model_validate(payload, context={"relax_greeting_lists": False})


@pytest.mark.asyncio
async def test_e2e_single_message_triager_to_tier_b_reply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Synthetic inbound text → triage → tier-B → coherent assistant text."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    registry = RegistrySnapshot(
        registry_version=1,
        tools=[
            RegistryIndexEntry(sort_name="tick", identifier="tick", display_line="tick — E2E"),
        ],
    )
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {"group_scope": "all", "relax_greeting_lists": False},
            "providers": {"tier_default": {"triager": "stub/model"}},
            "permissions": {"scope_narrowing": {"enabled": False}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    incoming_text = "run the health check on my workspace"

    triage = await triage_turn(
        workspace=ws,
        session=SessionView(session_id="e2e-sess"),
        incoming=ApprovedUserTurn(text=incoming_text),
        registry_snapshot=registry,
        triage_context=TriagePromptContext(current_message=incoming_text),
    )
    assert triage.complexity == ComplexityTier.B
    assert triage.intent == Intent.NEW_REQUEST
    assert "tick" in triage.tools

    plan = iter(
        [
            _openai_assistant_tool("load_tool", '{"name":"tick"}', call_id="c1"),
            _openai_assistant_tool("tick", "{}", call_id="c2"),
            _openai_assistant_text("Health check complete — all green."),
        ],
    )

    async def _seq(_req: dict[str, Any]) -> dict[str, Any]:
        return next(plan)

    exe, tool_set = _tick_executor()
    transport = _ScriptedChatTransport(_seq)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-e2e",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-e2e", regime=BudgetRegime.FREE_LOCAL),
    )
    workspace = WorkspaceConfig(
        schema_version=1,
        workspace_root=str(tmp_path),
        security=SecurityWorkspaceConfig(),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    outcome = await run_b_turn(
        workspace=workspace,
        session=SessionHandle(session_id="e2e-sess"),
        turn_id="e2e-turn-1",
        triage=triage,
        incoming_text=incoming_text,
        tool_set=tool_set,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=ToolContext(
            session_id="e2e-sess",
            workspace_path=tmp_path,
            workspace_id="e2e-ws",
            registry_version=tool_set.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="e2e-turn-1",
        ),
    )
    assert outcome.status == "completed"
    joined = " ".join(m.text for m in outcome.final_messages)
    assert "Health check complete" in joined
    assert triage.first_message  # Triager line precedes executor completion in product path
