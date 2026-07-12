"""W3 — block shell improvisation when file/search tools bound (msg=816cba)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sevn.agent.adapters.tier_b_tools import (
    FILE_SEARCH_BOUND_TOOLS,
    _dispatch_tool,
    should_block_shell_improvisation,
)
from sevn.agent.executors.b_harness import _bound_tools_bypassed_via_shell, run_b_turn
from sevn.agent.executors.b_types import BTierDeps, ResolvedTierBModel, SessionHandle, SteerInject
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.agent.triager.routing_policy import is_file_search_intent_message
from sevn.config.workspace_config import SecurityWorkspaceConfig, WorkspaceConfig
from sevn.tools.base import FunctionTool, ToolDefinition, ToolExecutor, enveloped_success
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.codes import ToolResultCode
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
        super().__init__(proxy_base_url="http://tier-b-w3.test.invalid")
        self._fn = fn
        self.requests: list[dict[str, Any]] = []

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        body = dict(request)
        self.requests.append(body)
        return await self._fn(body)


def _ctx() -> ToolContext:
    return ToolContext(
        session_id="s-w3",
        workspace_path=Path("/tmp"),
        workspace_id="w",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


def _run_ctx(deps: BTierDeps) -> MagicMock:
    ctx = MagicMock()
    ctx.deps = deps
    return ctx


def _triage(*, tools: list[str]) -> TriageResult:
    return TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it — searching.",
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


def _make_file_search_executor(
    *extra_tools: tuple[str, Callable[..., Any]],
) -> tuple[ToolExecutor, Any]:
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

    for tool_name, handler in extra_tools:
        tool_def = ToolDefinition(
            name=tool_name,
            category="terminal",
            description=f"{tool_name} tool",
            parameters={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        )
        exe.register(FunctionTool(tool_def, handler))

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
        registry_version=89,
        skill_descriptions=merged,
        skill_inventory={},
        mcp_definitions=(),
        mcp_names=frozenset(),
    )
    return exe, ts


def test_file_search_bound_tools_constant() -> None:
    """W3.1: locked D3 file/search bound set."""
    assert (
        frozenset(
            {"search_in_file", "read", "glob", "list_dir", "find_file"},
        )
        == FILE_SEARCH_BOUND_TOOLS
    )


def test_should_block_shell_improvisation_matrix() -> None:
    """W3.2: block shell only when file/search tools are triager-bound."""
    assert should_block_shell_improvisation("terminal_run", frozenset({"search_in_file"}))
    assert should_block_shell_improvisation("sandbox_exec", frozenset({"list_dir"}))
    assert not should_block_shell_improvisation("terminal_run", frozenset({"terminal_run"}))
    assert not should_block_shell_improvisation("search_in_file", frozenset({"search_in_file"}))


def test_bound_tools_bypassed_via_shell_helper() -> None:
    """W3.3: outcome helper detects shell bypass on file-search intent."""
    assert _bound_tools_bypassed_via_shell(
        triager_bound_tool_picks=["search_in_file"],
        successful_tools_called=frozenset({"terminal_run"}),
        incoming_text="search markdown for temperature",
    )
    assert not _bound_tools_bypassed_via_shell(
        triager_bound_tool_picks=["search_in_file"],
        successful_tools_called=frozenset({"search_in_file"}),
        incoming_text="search markdown for temperature",
    )
    assert is_file_search_intent_message("search markdown for temperature")


@pytest.mark.asyncio
async def test_dispatch_blocks_terminal_run_when_search_bound() -> None:
    """W3.2: ``terminal_run`` dispatch rejected when ``search_in_file`` is triager-bound."""
    steer = SteerInject()
    deps = BTierDeps(
        tool_executor=ToolExecutor(),
        tool_context_template=_ctx(),
        workspace_path=Path("/tmp"),
        registry_version=1,
        loaded_tools={"terminal_run"},
        triager_bound_tools=frozenset({"search_in_file"}),
        steer_buffer=steer,
    )
    deps.tool_executor.dispatch = AsyncMock(return_value='{"ok": true}')  # type: ignore[method-assign]
    definition = ToolDefinition(
        name="terminal_run",
        category="terminal",
        description="Run shell command",
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    )
    result = await _dispatch_tool(_run_ctx(deps), definition, {"command": "grep -r temperature ."})
    assert ToolResultCode.VALIDATION_ERROR in result
    assert "search_in_file" in result
    assert "shell grep" in result.lower()
    deps.tool_executor.dispatch.assert_not_called()  # type: ignore[attr-defined]
    assert steer.pop_pending() is not None


@pytest.mark.asyncio
async def test_816cba_shell_only_turn_fails_not_completed(tmp_path: Path) -> None:
    """msg=816cba: bound ``search_in_file``, model tries ``terminal_run`` → failed (not completed)."""

    async def _terminal(_ctx: ToolContext, **kwargs: Any) -> str:
        _ = kwargs
        return enveloped_success({"output": "temperature found via grep"})

    exe, ts = _make_file_search_executor(("terminal_run", _terminal))
    triage = _triage(tools=["search_in_file", "terminal_run"])
    steer = SteerInject()
    step = 0

    async def _shell_then_narrate(_req: dict[str, Any]) -> dict[str, Any]:
        nonlocal step
        step += 1
        if step == 1:
            return _openai_assistant_tool(
                "terminal_run",
                json.dumps({"command": "grep -r temperature *.md"}),
                call_id="c-shell",
            )
        if step == 2:
            return _openai_assistant_tool(
                "terminal_run",
                json.dumps({"command": "grep -r temperature workspace/"}),
                call_id="c-shell-2",
            )
        return _openai_assistant_text("Found temperature mentions via grep in notes.md.")

    transport = _ScriptedChatTransport(_shell_then_narrate)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s-816cba"),
        turn_id="t-816cba",
        triage=triage,
        incoming_text="search workspace markdown files for temperature — no shell",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=steer,
        tool_context=ToolContext(
            session_id="s-816cba",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-816cba",
        ),
        max_rounds=4,
    )
    assert outcome.status == "failed"
    assert "search_in_file" not in outcome.successful_tools_called
    assert "terminal_run" not in outcome.successful_tools_called
    assert outcome.failure_detail in {
        "triager_bound_tools_unused",
        "bound_tools_bypassed_via_shell",
    }


@pytest.mark.asyncio
async def test_bound_search_in_file_success_still_completes(tmp_path: Path) -> None:
    """W3.4: ``search_in_file`` path still works when bound."""
    exe, ts = _make_file_search_executor()
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
        return _openai_assistant_text("Found temperature in notes.md.")

    transport = _ScriptedChatTransport(_search_then_answer)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s-w3-ok"),
        turn_id="t-w3-ok",
        triage=triage,
        incoming_text="search markdown for temperature",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=steer,
        tool_context=ToolContext(
            session_id="s-w3-ok",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-w3-ok",
        ),
        max_rounds=4,
    )
    assert outcome.status == "completed"
    assert "search_in_file" in outcome.successful_tools_called
    assert steer.pop_pending() is None


@pytest.mark.asyncio
async def test_terminal_run_only_not_blocked(tmp_path: Path) -> None:
    """W3.5: triager ``tools=['terminal_run']`` only — shell not blocked."""

    async def _terminal(_ctx: ToolContext, **kwargs: Any) -> str:
        _ = kwargs
        return enveloped_success({"output": "installed package"})

    exe, ts = _make_file_search_executor(("terminal_run", _terminal))
    triage = _triage(tools=["terminal_run"])
    steer = SteerInject()
    step = 0

    async def _shell_then_answer(_req: dict[str, Any]) -> dict[str, Any]:
        nonlocal step
        step += 1
        if step == 1:
            return _openai_assistant_tool(
                "terminal_run",
                json.dumps({"command": "uv sync --extra browser"}),
                call_id="c-install",
            )
        return _openai_assistant_text("Package install finished.")

    transport = _ScriptedChatTransport(_shell_then_answer)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s-w3-shell"),
        turn_id="t-w3-shell",
        triage=triage,
        incoming_text="run uv sync --extra browser",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=steer,
        tool_context=ToolContext(
            session_id="s-w3-shell",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-w3-shell",
        ),
        max_rounds=4,
    )
    assert outcome.status == "completed"
    assert "terminal_run" in outcome.successful_tools_called
    assert steer.pop_pending() is None
