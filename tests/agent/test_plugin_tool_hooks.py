"""ToolExecutor integration with ``PluginHookChain`` (`specs/34-plugin-hooks.md` §4.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.plugins.hook import Block, PluginHookBase
from sevn.plugins.runner import PluginHookChain, RegisteredHook
from sevn.tools.base import (
    FunctionTool,
    ToolCall,
    ToolContext,
    ToolDefinition,
    ToolExecutor,
    enveloped_success,
)
from sevn.tools.codes import ToolResultCode
from sevn.tools.permissions import AllowAllPermissionPolicy


@pytest.mark.asyncio
async def test_plugin_hook_block_before_tool_body() -> None:
    """``Block`` from ``pre_tool_call`` returns without executing the tool."""

    class Gate(PluginHookBase):
        async def pre_tool_call(self, tool_name, args, ctx) -> object:  # type: ignore[no-untyped-def]
            _ = ctx
            if tool_name == "adder":
                return Block("blocked-by-plugin")
            return await super().pre_tool_call(tool_name, args, ctx)

    chain = PluginHookChain(
        (
            RegisteredHook(
                hook=Gate("gate.main"),
                plugin_id="g",
                distribution_name="d",
                entry_point_name="g",
                trust_owner=True,
            ),
        ),
    )

    async def adder(ctx, a: int = 0) -> str:  # type: ignore[no-untyped-def]
        _ = ctx
        return enveloped_success({"sum": a + 1})

    d = ToolDefinition(
        name="adder",
        category="test",
        description="add",
        parameters={
            "type": "object",
            "properties": {"a": {"type": "integer"}},
            "required": [],
        },
    )
    exe = ToolExecutor(default_timeout_seconds=5.0)
    exe.register(FunctionTool(d, adder))
    ctx = ToolContext(
        session_id="s",
        workspace_path=Path("/tmp"),
        workspace_id="w",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        turn_id="t1",
        executor_tier="B",
        plugin_hooks=chain,
    )
    out = await exe.dispatch(ctx, ToolCall(name="adder", arguments={"a": 1}))
    blob = json.loads(out)
    assert blob["ok"] is False
    assert blob["code"] == ToolResultCode.PERMISSION_DENIED.value


@pytest.mark.asyncio
async def test_plugin_hook_raised_on_pre_exception() -> None:
    """Exceptions in ``pre_tool_call`` map to ``PLUGIN_HOOK_RAISED``."""

    class Bad(PluginHookBase):
        async def pre_tool_call(self, tool_name, args, ctx) -> object:  # type: ignore[no-untyped-def]
            _ = (tool_name, args, ctx)
            raise RuntimeError("boom")

    chain = PluginHookChain(
        (
            RegisteredHook(
                hook=Bad("bad.main"),
                plugin_id="b",
                distribution_name="d",
                entry_point_name="b",
                trust_owner=True,
            ),
        ),
    )

    async def adder(ctx) -> str:  # type: ignore[no-untyped-def]
        _ = ctx
        return enveloped_success({})

    d = ToolDefinition(
        name="adder",
        category="test",
        description="add",
        parameters={"type": "object", "properties": {}},
    )
    exe = ToolExecutor(default_timeout_seconds=5.0)
    exe.register(FunctionTool(d, adder))
    ctx = ToolContext(
        session_id="s",
        workspace_path=Path("/tmp"),
        workspace_id="w",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        plugin_hooks=chain,
    )
    out = await exe.dispatch(ctx, ToolCall(name="adder", arguments={}))
    blob = json.loads(out)
    assert blob["ok"] is False
    assert blob["code"] == ToolResultCode.PLUGIN_HOOK_RAISED.value
    assert blob.get("data", {}).get("kind") == "plugin_hook_raised"
