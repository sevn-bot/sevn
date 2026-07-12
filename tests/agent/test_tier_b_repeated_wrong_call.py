"""Wave W12 — tier-B fails faster on repeated identical wrong tool calls."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.exceptions import UsageLimitExceeded

from sevn.agent.adapters.tier_b_tools import _dispatch_tool
from sevn.agent.executors.b_types import BTierDeps
from sevn.tools.base import ToolDefinition, ToolExecutor, enveloped_failure
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy


def _deps() -> BTierDeps:
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
    )


def _run_ctx(deps: BTierDeps) -> MagicMock:
    ctx = MagicMock()
    ctx.deps = deps
    return ctx


@pytest.mark.asyncio
async def test_skill_is_actually_tool_escalates_on_second_repeat() -> None:
    deps = _deps()
    definition = ToolDefinition(
        name="run_skill_runnable",
        category="skills",
        description="run skill",
        parameters={"type": "object", "properties": {"skill": {"type": "string"}}},
    )
    payload = {"skill": "serp"}
    envelope = enveloped_failure(
        "serp is a tool",
        code=ToolResultCode.SKILL_IS_ACTUALLY_TOOL,
    )
    deps.tool_executor.dispatch = AsyncMock(return_value=envelope)  # type: ignore[method-assign]

    await _dispatch_tool(_run_ctx(deps), definition, payload)
    with pytest.raises(UsageLimitExceeded, match="repeated wrong tool call"):
        await _dispatch_tool(_run_ctx(deps), definition, payload)

    assert deps.escalation is not None
    assert deps.escalation.reason == "repeated_wrong_tool_call"


@pytest.mark.asyncio
async def test_other_tool_errors_need_three_repeats() -> None:
    deps = _deps()
    definition = ToolDefinition(
        name="glob",
        category="file_ops",
        description="glob",
        parameters={"type": "object", "properties": {"pattern": {"type": "string"}}},
    )
    payload = {"pattern": "*.py"}
    envelope = enveloped_failure("bad pattern", code=ToolResultCode.VALIDATION_ERROR)
    deps.tool_executor.dispatch = AsyncMock(return_value=envelope)  # type: ignore[method-assign]
    deps.loaded_tools.add("glob")

    await _dispatch_tool(_run_ctx(deps), definition, payload)
    await _dispatch_tool(_run_ctx(deps), definition, payload)
    with pytest.raises(UsageLimitExceeded, match="repeated wrong tool call"):
        await _dispatch_tool(_run_ctx(deps), definition, payload)
