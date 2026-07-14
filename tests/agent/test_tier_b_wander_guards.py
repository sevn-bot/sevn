"""Tier-B wander-loop guards: duplicate-call dedup + per-turn tool-call budget."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from sevn.agent.adapters.tier_b_tools import _dispatch_tool
from sevn.agent.executors.b_types import BTierDeps
from sevn.config.defaults import TIER_B_TOOL_CALL_BUDGET, TIER_B_TOOL_FAILURE_HARD_CAP
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


def _read_def() -> ToolDefinition:
    return ToolDefinition(
        name="read",
        category="file_ops",
        description="read",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
    )


@pytest.mark.asyncio
async def test_dedup_skips_repeated_successful_read() -> None:
    deps = _deps()
    definition = _read_def()
    payload = {"path": "a.py"}
    deps.tool_executor.dispatch = AsyncMock(return_value='{"ok": true, "data": {}}')  # type: ignore[method-assign]

    first = await _dispatch_tool(_run_ctx(deps), definition, payload)
    assert '"ok": true' in first
    second = await _dispatch_tool(_run_ctx(deps), definition, payload)

    assert "Duplicate call" in second
    assert ToolResultCode.VALIDATION_ERROR.value in second
    # Executor dispatched only once — the repeat short-circuits before dispatch.
    assert deps.tool_executor.dispatch.call_count == 1


@pytest.mark.asyncio
async def test_dedup_does_not_fire_on_failed_prior_call() -> None:
    deps = _deps()
    definition = _read_def()
    payload = {"path": "missing.py"}
    deps.tool_executor.dispatch = AsyncMock(  # type: ignore[method-assign]
        return_value=enveloped_failure("not found", code=ToolResultCode.VALIDATION_ERROR),
    )

    await _dispatch_tool(_run_ctx(deps), definition, payload)
    await _dispatch_tool(_run_ctx(deps), definition, payload)

    # Failing calls are not deduped — both reach the executor (escalation path owns repeats).
    assert deps.tool_executor.dispatch.call_count == 2


@pytest.mark.asyncio
async def test_tool_call_budget_blocks_after_cap() -> None:
    deps = _deps()
    definition = _read_def()
    deps.tool_call_counts = {f"x{i}": 1 for i in range(TIER_B_TOOL_CALL_BUDGET)}
    deps.tool_executor.dispatch = AsyncMock(return_value='{"ok": true, "data": {}}')  # type: ignore[method-assign]

    result = await _dispatch_tool(_run_ctx(deps), definition, {"path": "z.py"})

    assert f"Tool-call budget ({TIER_B_TOOL_CALL_BUDGET})" in result
    assert deps.tool_executor.dispatch.call_count == 0


@pytest.mark.asyncio
async def test_tool_failure_hard_cap_stops_varying_args_loop() -> None:
    """A tool failing with *different* args each time is blocked at the failure cap.

    The identical-call escalation keys on repeated same-args calls, so varying the
    payload keeps ``repeat_n == 1``; the per-tool failure hard cap is what stops the
    loop (mirrors the live ESPN / run_code failures that varied args each attempt).
    """
    deps = _deps()
    definition = _read_def()
    deps.tool_executor.dispatch = AsyncMock(  # type: ignore[method-assign]
        return_value=enveloped_failure("boom", code=ToolResultCode.VALIDATION_ERROR),
    )

    results = [
        await _dispatch_tool(_run_ctx(deps), definition, {"path": f"f{i}.py"})
        for i in range(TIER_B_TOOL_FAILURE_HARD_CAP)
    ]

    # All attempts reached the executor (varying args are never deduped)...
    assert deps.tool_executor.dispatch.call_count == TIER_B_TOOL_FAILURE_HARD_CAP
    # ...but the final one is replaced with the terminal "stop calling it" steer.
    assert "stop calling it" in results[-1]
    assert f"failed {TIER_B_TOOL_FAILURE_HARD_CAP} times" in results[-1]
    assert "boom" in results[0]
