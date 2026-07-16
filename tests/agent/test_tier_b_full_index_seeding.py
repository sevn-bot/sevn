"""W1 — full-index triager-bound seeding + skill preservation (msg=4f8208, 62803d)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sevn.agent.adapters.tier_b_tools import (
    _NEVER_LAZY_NAMES,
    _dispatch_tool,
    prepare_lazy_tool_definitions,
)
from sevn.agent.executors.b_harness import run_b_turn
from sevn.agent.executors.b_types import ResolvedTierBModel, SessionHandle
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.config.workspace_config import SecurityWorkspaceConfig, WorkspaceConfig
from sevn.tools.base import ToolDefinition, ToolExecutor
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry

_LIST_DIR_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "return_only": {"type": "string"},
    },
    "required": [],
}


def _openai_assistant_text(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class _ScriptedChatTransport(ChatCompletionsTransport):
    def __init__(self, fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> None:
        super().__init__(proxy_base_url="http://tier-b-full-index.test.invalid")
        self._fn = fn

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        return await self._fn(dict(request))


def _workspace(tmp: Path) -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        workspace_root=str(tmp),
        security=SecurityWorkspaceConfig(),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


def _triage(
    *,
    tools: list[str] | None = None,
    skills: list[str] | None = None,
) -> TriageResult:
    return TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=tools or [],
        skills=skills or [],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )


def _deps(loaded_tools: set[str]) -> Any:
    from sevn.agent.executors.b_types import BTierDeps

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
        loaded_tools=loaded_tools,
    )


def _run_ctx(deps: Any) -> MagicMock:
    ctx = MagicMock()
    ctx.deps = deps
    return ctx


def _pa_tool(name: str, schema: dict[str, object] | None = None) -> Any:
    from pydantic_ai.tools import ToolDefinition as PAToolDefinition

    return PAToolDefinition(
        name=name,
        description=f"{name} description",
        parameters_json_schema=schema or _LIST_DIR_SCHEMA,
    )


# ---------------------------------------------------------------------------
# W1.1 — harness seed formula (D1)
# ---------------------------------------------------------------------------


def test_full_index_triager_bound_seed_formula() -> None:
    """msg=4f8208: triager ``list_dir`` stays seeded when catalog exceeds 7 tools."""
    triager_picks = frozenset({"list_dir", "load_tool"})
    seeded = set(triager_picks) - _NEVER_LAZY_NAMES
    assert "list_dir" in seeded
    assert "load_tool" not in seeded


def test_full_index_seed_does_not_include_unpicked_catalog_tools() -> None:
    """D1: only triager picks are seeded — not the widened ~40-tool catalog."""
    triager_picks = frozenset({"list_dir"})
    catalog = frozenset(f"tool_{i}" for i in range(40))
    seeded = set(triager_picks) - _NEVER_LAZY_NAMES
    assert seeded == {"list_dir"}
    assert seeded.isdisjoint(catalog - {"list_dir"})


# ---------------------------------------------------------------------------
# W1.2 / W1.4 — prepare_lazy + dispatch without load_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_lazy_list_dir_seeded_full_schema_on_full_index() -> None:
    """W1.2: pre-seeded ``list_dir`` exposes full JSON schema (not stub banner)."""
    deps = _deps(loaded_tools={"list_dir"})
    ctx = _run_ctx(deps)
    defs = [_pa_tool("list_dir", _LIST_DIR_SCHEMA)]
    result = await prepare_lazy_tool_definitions(ctx, defs)
    assert result is not None
    td = result[0]
    assert td.parameters_json_schema.get("properties")
    assert "[SCHEMA NOT YET LOADED]" not in (td.description or "")


@pytest.mark.asyncio
async def test_dispatch_list_dir_without_load_tool_when_seeded() -> None:
    """msg=4f8208: ``list_dir`` callable on full-index without prior ``load_tool``."""
    deps = _deps(loaded_tools={"list_dir"})
    ok_envelope = json.dumps({"ok": True, "data": {"entries": []}})
    deps.tool_executor.dispatch = AsyncMock(return_value=ok_envelope)  # type: ignore[method-assign]
    ctx = _run_ctx(deps)
    definition = ToolDefinition(
        name="list_dir",
        category="file_ops",
        description="List directory",
        parameters=_LIST_DIR_SCHEMA,  # type: ignore[arg-type]
    )
    result = await _dispatch_tool(ctx, definition, {"path": "."})
    assert "not loaded" not in result
    assert ToolResultCode.VALIDATION_ERROR not in result
    deps.tool_executor.dispatch.assert_called_once()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# W1.4 / W1.5 — harness integration via tier_b.input debug_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_index_retry_seeds_list_dir_in_tier_b_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """msg=4f8208: full_index retry logs ``seeded_tools`` containing ``list_dir``."""
    exe, ts = build_session_registry(registry_version=42, workspace_root=tmp_path)
    assert len(exe.definitions()) > 7

    captured: list[dict[str, object]] = []

    def _capture(event: str, **fields: object) -> None:
        if event == "tier_b.input":
            captured.append(dict(fields))

    monkeypatch.setattr("sevn.logging.structured.debug_event", _capture)

    async def _text_only(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text("done.")

    transport = _ScriptedChatTransport(_text_only)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s-fi"),
        turn_id="t-fi-list",
        triage=_triage(tools=["list_dir"]),
        incoming_text="list workspace folders",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=ToolContext(
            session_id="s-fi",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-fi-list",
        ),
        full_index=True,
        max_rounds=2,
    )

    assert captured
    input_event = captured[0]
    assert input_event.get("full_index") is True
    assert "list_dir" in (input_event.get("seeded_tools") or [])


@pytest.mark.asyncio
async def test_full_index_retry_preserves_browser_skill_in_tier_b_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """msg=62803d: full_index retry keeps ``browser-harness`` in ``tier_b.input skills``."""
    exe, ts = build_session_registry(registry_version=43, workspace_root=tmp_path)

    captured: list[dict[str, object]] = []

    def _capture(event: str, **fields: object) -> None:
        if event == "tier_b.input":
            captured.append(dict(fields))

    monkeypatch.setattr("sevn.logging.structured.debug_event", _capture)

    async def _text_only(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text("done.")

    transport = _ScriptedChatTransport(_text_only)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s-fi-skill"),
        turn_id="t-fi-skill",
        triage=_triage(tools=["run_skill_script", "send_file"], skills=["browser-harness"]),
        incoming_text="screenshot https://example.com",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=ToolContext(
            session_id="s-fi-skill",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-fi-skill",
        ),
        full_index=True,
        max_rounds=2,
    )

    assert captured
    input_event = captured[0]
    assert input_event.get("full_index") is True
    assert "browser-harness" in (input_event.get("skills") or [])
