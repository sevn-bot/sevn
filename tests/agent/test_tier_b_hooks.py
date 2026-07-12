"""W5 — tier-B registry toolset + lifecycle hooks."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai._agent_graph import ModelRequestNode
from pydantic_ai.capabilities import ValidatedToolArgs
from pydantic_ai.exceptions import ModelRetry, SkipToolExecution, UsageLimitExceeded
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.tools import DeferredToolRequests
from pydantic_ai.tools import ToolDefinition as PAToolDefinition
from pydantic_ai.usage import RunUsage

from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
from sevn.agent.adapters.tier_b_hooks import (
    TierBHookConfig,
    build_tier_b_hooks,
    check_permission_before_dispatch,
    enforce_round_budget,
    fetch_round_cap_after_model,
    grounding_guard_after_model,
    inject_owner_steer,
    permission_before_tool_execute,
    provision_denial_envelope,
    resolve_deferred_approvals,
)
from sevn.agent.adapters.tier_b_tools import _dispatch_tool, _make_registry_tool
from sevn.agent.adapters.tier_b_toolset import SevnRegistryToolset
from sevn.agent.executors.b_harness import build_tier_b_capabilities
from sevn.agent.executors.b_types import BTierDeps, SteerInject
from sevn.tools.base import FunctionTool, ToolCall, ToolDefinition, ToolExecutor, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy


def _ctx() -> ToolContext:
    return ToolContext(
        session_id="s",
        workspace_path=Path("/tmp"),
        workspace_id="w",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


def _deps(*, loaded: set[str] | None = None, steer: SteerInject | None = None) -> BTierDeps:
    return BTierDeps(
        tool_executor=ToolExecutor(),
        tool_context_template=_ctx(),
        workspace_path=Path("/tmp"),
        registry_version=1,
        loaded_tools=loaded or set(),
        steer_buffer=steer,
    )


def _hook_config(**overrides: object) -> TierBHookConfig:
    base = {
        "provider_round_counter": [0],
        "max_rounds": 2,
        "count_planning": False,
        "bound_tool_names": frozenset({"serp"}),
        "triager_first_reply": "",
    }
    base.update(overrides)
    return TierBHookConfig(**base)  # type: ignore[arg-type]


def _run_ctx(deps: BTierDeps) -> RunContext[BTierDeps]:
    return RunContext(deps=deps, model=MagicMock(), usage=RunUsage())


def test_fetch_round_steer_not_before_round_four() -> None:
    config = _hook_config(provider_round_counter=[2])
    steer = SteerInject()
    deps = _deps(steer=steer)
    deps.successful_tools_called.add("get_page_content")
    ctx = _run_ctx(deps)
    response = ModelResponse(parts=[TextPart(content="")])
    fetch_round_cap_after_model(config, ctx, response)
    assert steer.pending_text is None
    assert deps.fetch_round_steer_injected is False


def test_fetch_round_steer_injects_once_at_round_four() -> None:
    config = _hook_config(provider_round_counter=[4])
    steer = SteerInject()
    deps = _deps(steer=steer)
    deps.successful_tools_called.add("get_page_content")
    ctx = _run_ctx(deps)
    response = ModelResponse(parts=[TextPart(content="")])
    fetch_round_cap_after_model(config, ctx, response)
    assert steer.pending_text is not None
    assert "Do NOT re-fetch" in steer.pending_text
    assert deps.fetch_round_steer_injected is True


def test_fetch_round_steer_skips_duplicate_on_later_round() -> None:
    config = _hook_config(provider_round_counter=[5])
    steer = SteerInject(pending_text="existing steer")
    deps = _deps(steer=steer)
    deps.successful_tools_called.add("get_page_content")
    deps.fetch_round_steer_injected = True
    ctx = _run_ctx(deps)
    response = ModelResponse(parts=[TextPart(content="")])
    fetch_round_cap_after_model(config, ctx, response)
    assert steer.pending_text == "existing steer"


def test_fetch_round_steer_skips_when_answer_delivered() -> None:
    config = _hook_config(provider_round_counter=[4])
    steer = SteerInject()
    deps = _deps(steer=steer)
    deps.successful_tools_called.add("get_page_content")
    ctx = _run_ctx(deps)
    response = ModelResponse(
        parts=[TextPart(content="1. Headline one\n2. Headline two")],
    )
    fetch_round_cap_after_model(config, ctx, response)
    assert steer.pending_text is None
    assert deps.fetch_round_steer_injected is False


@pytest.mark.asyncio
async def test_steer_hook_appends_owner_steer_message() -> None:
    steer = SteerInject(pending_text="use serp now")
    deps = _deps(steer=steer)
    ctx = _run_ctx(deps)
    request_context = ModelRequestContext(
        model=MagicMock(),
        messages=[ModelRequest(parts=[UserPromptPart(content="hello")])],
        model_settings=None,
        model_request_parameters=MagicMock(),
    )
    out = await inject_owner_steer(ctx, request_context)
    assert len(out.messages) == 1
    assert "[Owner steer] use serp now" in out.messages[0].parts[-1].content  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_budget_hook_raises_usage_limit_exceeded() -> None:
    config = _hook_config(provider_round_counter=[2], max_rounds=2)
    ctx = _run_ctx(_deps())
    node = ModelRequestNode(request=ModelRequest(parts=[UserPromptPart(content="hi")]))
    with pytest.raises(UsageLimitExceeded):
        await enforce_round_budget(config, ctx, node=node)


def test_provision_denial_for_unloaded_tool() -> None:
    denial = provision_denial_envelope(_deps(), "serp")
    assert denial is not None
    blob = json.loads(denial)
    assert blob["code"] == ToolResultCode.TOOL_NOT_PROVISIONED


@pytest.mark.asyncio
async def test_permission_hook_skips_unprovisioned_tool() -> None:
    ctx = _run_ctx(_deps())
    call = ToolCallPart(tool_name="serp", args={"query": "x"}, tool_call_id="tc1")
    tool_def = PAToolDefinition(
        name="serp",
        parameters_json_schema={"type": "object", "properties": {}},
        description="search",
    )
    with pytest.raises(SkipToolExecution) as exc:
        await permission_before_tool_execute(
            ctx,
            call=call,
            tool_def=tool_def,
            args=ValidatedToolArgs({}),
        )
    blob = json.loads(exc.value.result)
    assert blob["code"] == ToolResultCode.TOOL_NOT_PROVISIONED


@pytest.mark.asyncio
async def test_grounding_hook_retries_on_unavailable_claim() -> None:
    config = _hook_config(bound_tool_names=frozenset({"serp"}))
    steer = SteerInject()
    ctx = _run_ctx(_deps(steer=steer))
    response = ModelResponse(
        parts=[
            TextPart(content="serp isn't in my current callable function list."),
        ],
    )
    with pytest.raises(ModelRetry):
        await grounding_guard_after_model(config, ctx, response)
    assert steer.pending_text is not None
    assert "serp" in steer.pending_text


@pytest.mark.asyncio
async def test_deferred_approval_denies_without_human_ack() -> None:
    ctx = _run_ctx(_deps())
    requests = DeferredToolRequests(
        approvals=[
            ToolCallPart(tool_name="delete", args={"path": "x"}, tool_call_id="del1"),
        ],
    )
    results = await resolve_deferred_approvals(ctx, requests=requests)
    assert results.approvals["del1"] is not True


def test_delete_tool_marks_requires_approval() -> None:
    defn = ToolDefinition(
        name="delete",
        category="file",
        description="delete",
        parameters={"type": "object", "properties": {}},
        requires_human=True,
    )
    tool = _make_registry_tool(defn)
    assert tool.requires_approval is True


@pytest.mark.asyncio
async def test_sevn_registry_toolset_dispatches_via_executor() -> None:
    exe = ToolExecutor()

    async def _read_body(ctx: ToolContext) -> str:
        return enveloped_success({"text": "ok"})

    exe.register(
        FunctionTool(
            ToolDefinition(
                name="read",
                category="file",
                description="read",
                parameters={"type": "object", "properties": {}},
            ),
            _read_body,
        ),
    )
    reg = PydanticToolRegistration(("read",), {"read": "read file"}, (), {})
    toolset = SevnRegistryToolset.from_registry(exe, reg)
    deps = BTierDeps(
        tool_executor=exe,
        tool_context_template=_ctx(),
        workspace_path=Path("/tmp"),
        registry_version=1,
        loaded_tools={"read"},
    )
    ctx = _run_ctx(deps)
    tools = await toolset.get_tools(ctx)
    assert "read" in tools
    raw = await toolset.call_tool("read", {}, ctx, tools["read"])
    blob = json.loads(raw)
    assert blob["ok"] is True


def test_check_permission_blocks_delete_without_ack() -> None:
    exe = ToolExecutor()
    exe.register(
        FunctionTool(
            ToolDefinition(
                name="delete",
                category="file",
                description="delete",
                parameters={"type": "object", "properties": {}},
                requires_human=True,
            ),
            lambda _ctx: enveloped_success({"deleted": True}),
        ),
    )
    deps = BTierDeps(
        tool_executor=exe,
        tool_context_template=_ctx(),
        workspace_path=Path("/tmp"),
        registry_version=1,
        loaded_tools={"delete"},
    )
    denial = check_permission_before_dispatch(deps, "delete")
    assert denial is not None
    assert json.loads(denial)["code"] == ToolResultCode.PLAN_HUMAN_GATE


def test_build_tier_b_capabilities_includes_hooks_and_prepare_tools() -> None:
    hooks = build_tier_b_hooks(_hook_config())
    caps = build_tier_b_capabilities(hooks=hooks)
    assert caps[0].__class__.__name__ == "Instrumentation"
    assert caps[1].__class__.__name__ == "Hooks"
    assert caps[2].__class__.__name__ == "PrepareTools"


@pytest.mark.asyncio
async def test_dispatch_tool_calls_executor_dispatch() -> None:
    exe = ToolExecutor()
    dispatch = AsyncMock(return_value=enveloped_success({"ok": True}))
    exe.dispatch = dispatch  # type: ignore[method-assign]
    deps = BTierDeps(
        tool_executor=exe,
        tool_context_template=_ctx(),
        workspace_path=Path("/tmp"),
        registry_version=1,
        loaded_tools={"read"},
    )
    defn = ToolDefinition(
        name="read",
        category="file",
        description="read",
        parameters={"type": "object", "properties": {}},
    )
    ctx = _run_ctx(deps)
    await _dispatch_tool(ctx, defn, {})
    dispatch.assert_awaited_once()
    awaited_call = dispatch.await_args.args[1]
    assert isinstance(awaited_call, ToolCall)
    assert awaited_call.name == "read"
