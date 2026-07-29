"""W1.9 — hooks→guardrails parity for permission/budget/approval (D7, W8)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai._agent_graph import ModelRequestNode
from pydantic_ai.exceptions import SkipToolExecution, UsageLimitExceeded
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.tools import ToolDefinition as PAToolDefinition
from pydantic_ai.usage import RunUsage

from sevn.agent.adapters.tier_b_hooks import (
    TierBHookConfig,
    enforce_round_budget,
    grounding_guard_after_model,
    inject_owner_steer,
    permission_before_tool_execute,
)
from sevn.agent.executors.b_types import BTierDeps, SteerInject
from sevn.tools.base import ToolExecutor
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


def _deps(*, steer: SteerInject | None = None) -> BTierDeps:
    return BTierDeps(
        tool_executor=ToolExecutor(),
        tool_context_template=_ctx(),
        workspace_path=Path("/tmp"),
        registry_version=1,
        steer_buffer=steer,
    )


def _run_ctx(deps: BTierDeps) -> RunContext[BTierDeps]:
    return RunContext(deps=deps, model=MagicMock(), usage=RunUsage())


def _hook_config(**overrides: object) -> TierBHookConfig:
    base = {
        "provider_round_counter": [0],
        "max_rounds": 1,
        "count_planning": False,
        "bound_tool_names": frozenset({"serp"}),
        "triager_first_reply": "",
    }
    base.update(overrides)
    return TierBHookConfig(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_steer_hook_remains_sevn_owned() -> None:
    """Steer injection stays on sevn hooks — not migrated to harness guardrails."""
    deps = _deps(steer=SteerInject(pending_text="operator steer text"))
    ctx = _run_ctx(deps)
    request_context = ModelRequestContext(
        model=MagicMock(),
        messages=[ModelRequest(parts=[UserPromptPart(content="hello")])],
        model_settings=None,
        model_request_parameters=MagicMock(),
    )
    updated = await inject_owner_steer(ctx, request_context)
    assert "[Owner steer] operator steer text" in updated.messages[0].parts[-1].content  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_grounding_hook_remains_sevn_owned() -> None:
    """Grounding guard stays sevn-owned after W8."""
    cfg = _hook_config(triager_first_reply="grounded reply required")
    deps = _deps()
    ctx = _run_ctx(deps)
    response = ModelResponse(parts=[TextPart(content="ungrounded")])

    result = await grounding_guard_after_model(cfg, ctx, response)
    assert result is response


@pytest.mark.xfail(reason="green after W8: permission gate guardrail parity", strict=False)
@pytest.mark.asyncio
async def test_permission_gate_matches_harness_guardrail() -> None:
    from sevn.agent.adapters.tier_b_guardrails import permission_guardrail

    cfg = _hook_config(bound_tool_names=frozenset({"serp"}))
    deps = _deps()
    ctx = _run_ctx(deps)
    call = ToolCallPart(tool_name="delete", args={}, tool_call_id="c1")
    tool_def = PAToolDefinition(name="delete", description="", parameters_json_schema={})

    with pytest.raises(SkipToolExecution):
        await permission_before_tool_execute(ctx, call=call, tool_def=tool_def, args={})

    guard = permission_guardrail(cfg)
    with pytest.raises(SkipToolExecution):
        await guard.check_tool_access(ctx, tool_name="delete", args={})


@pytest.mark.xfail(reason="green after W8: round budget guardrail parity", strict=False)
@pytest.mark.asyncio
async def test_budget_enforcement_matches_harness_guardrail() -> None:
    from sevn.agent.adapters.tier_b_guardrails import round_budget_guardrail

    cfg = _hook_config(max_rounds=0)
    deps = _deps()
    ctx = _run_ctx(deps)
    node = ModelRequestNode(request=ModelRequest(parts=[UserPromptPart(content="hi")]))

    with pytest.raises(UsageLimitExceeded):
        await enforce_round_budget(cfg, ctx, node=node)

    guard = round_budget_guardrail(cfg)
    with pytest.raises(UsageLimitExceeded):
        await guard.check_before_node(ctx, node=node)


@pytest.mark.xfail(reason="green after W8: approval workflow guardrail parity", strict=False)
@pytest.mark.asyncio
async def test_deferred_approval_matches_harness_guardrail() -> None:
    from sevn.agent.adapters.tier_b_guardrails import approval_guardrail

    cfg = _hook_config()
    deps = _deps()
    ctx = _run_ctx(deps)
    bridge = MagicMock()
    bridge.await_approval = AsyncMock(return_value=False)
    ctx.deps.approval_bridge = bridge  # type: ignore[attr-defined]

    guard = approval_guardrail(cfg)
    denied = await guard.resolve(ctx, tool_name="delete", args={})
    assert denied is not None
