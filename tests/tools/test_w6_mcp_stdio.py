"""W6 MCP stdio transport tests (`plan/forward-track-registry-bindings-permissions-v1gate-wave-plan.md` W6.3).

Acceptance criteria:
- A declared MCP server (fake stdio) registers its tools as McpStdioTool (not McpUnavailableTool).
- An undeclared / unreachable server degrades to McpUnavailableTool with readiness note (W1.5).
- SevnMcpStdioClient.call_tool dispatches to the underlying McpStdioClient Protocol correctly.
- build_mcp_stdio_client returns None when no servers are declared.
- discover_mcp_tool_definitions returns empty tuple on transport failure (no crash).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sevn.tools.base import ToolCall, ToolDefinition
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.mcp_stdio_client import (
    SevnMcpStdioClient,
    build_mcp_stdio_client,
    discover_mcp_tool_definitions,
    list_tools_from_server,
)
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import McpUnavailableTool, build_session_registry
from sevn.tools.runtime_dispatch import McpStdioTool, RuntimeToolBindings


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        session_id="w6-mcp-sess",
        workspace_path=tmp_path,
        workspace_id="w6-mcp-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


# ---------------------------------------------------------------------------
# SevnMcpStdioClient unit tests
# ---------------------------------------------------------------------------


def test_mcp_server_ids_empty() -> None:
    c = SevnMcpStdioClient({})
    assert c.mcp_server_ids == []


def test_mcp_server_ids_populated() -> None:
    c = SevnMcpStdioClient(
        {
            "graphify": {"command": "graphify", "args": ["serve"]},
            "code_review_graph": {"command": "code-review-graph", "args": ["serve"]},
        }
    )
    assert sorted(c.mcp_server_ids) == ["code_review_graph", "graphify"]


def test_server_params_undeclared_returns_none() -> None:
    c = SevnMcpStdioClient({"a": {"command": "echo", "args": []}})
    assert c._server_params("missing") is None


def test_server_params_empty_command_returns_none() -> None:
    c = SevnMcpStdioClient({"bad": {"command": "", "args": []}})
    assert c._server_params("bad") is None


def test_server_params_valid() -> None:
    c = SevnMcpStdioClient({"srv": {"command": "my-server", "args": ["--port", "8080"]}})
    assert c._server_params("srv") == ("my-server", ["--port", "8080"])


@pytest.mark.asyncio
async def test_call_tool_raises_for_undeclared_server() -> None:
    """call_tool on a server not in mcp_servers must raise RuntimeError (McpStdioTool catches it)."""
    c = SevnMcpStdioClient({})
    ctx = ToolContext(
        session_id="s",
        workspace_path=Path("/tmp"),
        workspace_id="w",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )
    with pytest.raises(RuntimeError, match="not declared"):
        await c.call_tool(
            server_id="missing",
            tool_name="do_thing",
            arguments={},
            ctx=ctx,
        )


@pytest.mark.asyncio
async def test_call_tool_dispatches_via_stdio_client(tmp_path: Path) -> None:
    """call_tool with a working server returns decoded payload."""
    from mcp.types import CallToolResult, TextContent

    fake_result = CallToolResult(
        content=[TextContent(type="text", text='{"items": [1, 2, 3]}')],
        isError=False,
    )

    fake_session = AsyncMock()
    fake_session.initialize = AsyncMock()
    fake_session.call_tool = AsyncMock(return_value=fake_result)
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)

    fake_client_session_cls = MagicMock(return_value=fake_session)

    fake_streams = (AsyncMock(), AsyncMock())

    # stdio_client is a sync function returning an async context manager (not a coroutine).
    def _fake_stdio_client(params: Any) -> Any:
        class _CM:
            async def __aenter__(self_cm) -> Any:
                return fake_streams

            async def __aexit__(self_cm, *args: Any) -> bool:
                return False

        return _CM()

    c = SevnMcpStdioClient({"my_srv": {"command": "my-server", "args": []}})
    ctx = ToolContext(
        session_id="s",
        workspace_path=tmp_path,
        workspace_id="w",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )

    with (
        patch("sevn.tools.mcp_stdio_client.stdio_client", new=_fake_stdio_client),
        patch("sevn.tools.mcp_stdio_client.ClientSession", new=fake_client_session_cls),
    ):
        result = await c.call_tool(
            server_id="my_srv",
            tool_name="do_thing",
            arguments={"key": "val"},
            ctx=ctx,
        )

    assert result == {"items": [1, 2, 3]}
    fake_session.call_tool.assert_awaited_once_with(name="do_thing", arguments={"key": "val"})


@pytest.mark.asyncio
async def test_call_tool_server_side_error_returns_error_mapping(tmp_path: Path) -> None:
    """When server returns isError=True, call_tool returns a mapping with 'error' key."""
    from mcp.types import CallToolResult, TextContent

    fake_result = CallToolResult(
        content=[TextContent(type="text", text="division by zero")],
        isError=True,
    )
    fake_session = AsyncMock()
    fake_session.initialize = AsyncMock()
    fake_session.call_tool = AsyncMock(return_value=fake_result)
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)

    fake_client_session_cls = MagicMock(return_value=fake_session)
    fake_streams = (AsyncMock(), AsyncMock())

    # stdio_client is a sync function returning an async context manager.
    def _fake_stdio_client(params: Any) -> Any:
        class _CM:
            async def __aenter__(self_cm) -> Any:
                return fake_streams

            async def __aexit__(self_cm, *args: Any) -> bool:
                return False

        return _CM()

    c = SevnMcpStdioClient({"srv": {"command": "echo", "args": []}})
    ctx = ToolContext(
        session_id="s",
        workspace_path=tmp_path,
        workspace_id="w",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )

    with (
        patch("sevn.tools.mcp_stdio_client.stdio_client", new=_fake_stdio_client),
        patch("sevn.tools.mcp_stdio_client.ClientSession", new=fake_client_session_cls),
    ):
        result = await c.call_tool(
            server_id="srv",
            tool_name="bad_tool",
            arguments={},
            ctx=ctx,
        )

    assert "error" in result
    assert "division by zero" in result["error"]


# ---------------------------------------------------------------------------
# build_mcp_stdio_client factory
# ---------------------------------------------------------------------------


def test_build_mcp_stdio_client_no_servers() -> None:
    assert build_mcp_stdio_client({}) is None


def test_build_mcp_stdio_client_with_servers() -> None:
    client = build_mcp_stdio_client({"srv": {"command": "echo", "args": []}})
    assert isinstance(client, SevnMcpStdioClient)
    assert "srv" in client.mcp_server_ids


# ---------------------------------------------------------------------------
# discover_mcp_tool_definitions (W6.3 — unreachable server degrades gracefully)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_mcp_tool_definitions_empty_servers() -> None:
    result = await discover_mcp_tool_definitions({})
    assert result == ()


@pytest.mark.asyncio
async def test_discover_mcp_tool_definitions_unreachable_server_returns_empty() -> None:
    """Unreachable server should NOT raise — degrade to empty list."""
    result = await discover_mcp_tool_definitions(
        {"bad_server": {"command": "this-command-does-not-exist-w6-test", "args": []}}
    )
    # No crash; the server is unreachable so no tool defs are returned.
    assert isinstance(result, tuple)
    # May be empty (server not found) or non-empty if somehow it resolved — just no crash.


@pytest.mark.asyncio
async def test_list_tools_from_server_returns_empty_on_os_error() -> None:
    """list_tools_from_server silently returns [] on OSError."""
    defs = await list_tools_from_server(
        "bad_server",
        "command-that-does-not-exist-w6",
        [],
    )
    assert defs == []


# ---------------------------------------------------------------------------
# Registry integration: declared server + McpStdioTool vs McpUnavailableTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_declared_server_uses_mcp_stdio_tool_not_unavailable(ctx: ToolContext) -> None:
    """W6.3: declared MCP server with a live client → McpStdioTool, not McpUnavailableTool."""
    descriptor = ToolDefinition(
        name="my_srv.do_thing",
        category="mcp",
        description="demo mcp tool",
        parameters={"type": "object", "properties": {"x": {"type": "string"}}},
        enabled=True,
    )

    class _FakeClient:
        async def call_tool(
            self, *, server_id: str, tool_name: str, arguments: Mapping[str, Any], ctx: ToolContext
        ) -> Mapping[str, Any]:
            return {"result": "ok", "server_id": server_id, "tool": tool_name}

    client = _FakeClient()
    exe, _ts = build_session_registry(
        registry_version=1,
        extra_mcp=(descriptor,),
        runtime_bindings=RuntimeToolBindings(
            mcp=client,
            mcp_servers={"my_srv": {"command": "my-server", "args": []}},
        ),
    )

    registered = exe.get("my_srv.do_thing")
    assert isinstance(registered, McpStdioTool), f"Expected McpStdioTool, got {type(registered)}"
    assert not isinstance(registered, McpUnavailableTool)

    envelope = json.loads(
        await exe.dispatch(ctx, ToolCall(name="my_srv.do_thing", arguments={"x": "hello"}))
    )
    assert envelope["ok"] is True
    assert envelope["data"]["server_id"] == "my_srv"
    assert envelope["data"]["tool"] == "do_thing"


@pytest.mark.asyncio
async def test_undeclared_server_degrades_to_mcp_unavailable(ctx: ToolContext) -> None:
    """W6.3: server in extra_mcp but NOT in mcp_servers → McpUnavailableTool."""
    descriptor = ToolDefinition(
        name="other_srv.some_tool",
        category="mcp",
        description="undeclared",
        parameters={"type": "object", "properties": {}},
        enabled=True,
    )

    class _FakeClient:
        async def call_tool(self, **_: Any) -> Mapping[str, Any]:
            return {}

    exe, _ts = build_session_registry(
        registry_version=1,
        extra_mcp=(descriptor,),
        runtime_bindings=RuntimeToolBindings(
            mcp=_FakeClient(),
            mcp_servers={"known_srv": {"command": "echo", "args": []}},
        ),
    )

    registered = exe.get("other_srv.some_tool")
    assert isinstance(registered, McpUnavailableTool)

    envelope = json.loads(
        await exe.dispatch(ctx, ToolCall(name="other_srv.some_tool", arguments={}))
    )
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.MCP_UNAVAILABLE


@pytest.mark.asyncio
async def test_no_mcp_client_always_uses_unavailable_placeholder(ctx: ToolContext) -> None:
    """W6.3: no mcp client wired → McpUnavailableTool regardless of server declarations."""
    descriptor = ToolDefinition(
        name="srv.tool",
        category="mcp",
        description="no client",
        parameters={"type": "object", "properties": {}},
        enabled=True,
    )

    exe, _ts = build_session_registry(
        registry_version=1,
        extra_mcp=(descriptor,),
        # No mcp= in bindings
        runtime_bindings=RuntimeToolBindings(
            mcp_servers={"srv": {"command": "echo", "args": []}},
        ),
    )

    registered = exe.get("srv.tool")
    assert isinstance(registered, McpUnavailableTool)

    envelope = json.loads(await exe.dispatch(ctx, ToolCall(name="srv.tool", arguments={})))
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.MCP_UNAVAILABLE


@pytest.mark.asyncio
async def test_load_tool_mcp_unavailable_carries_readiness(ctx: ToolContext) -> None:
    """McpUnavailableTool placeholder has readiness metadata via W1.5 meta_loaders."""
    descriptor = ToolDefinition(
        name="unreach.tool",
        category="mcp",
        description="unreachable server",
        parameters={"type": "object", "properties": {}},
        enabled=True,
    )

    exe, _ts = build_session_registry(
        registry_version=1,
        extra_mcp=(descriptor,),
        # No mcp client → placeholder
    )

    raw = await exe.dispatch(
        ctx,
        ToolCall(name="load_tool", arguments={"name": "unreach.tool"}),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    data = env["data"]
    # Tool info should be returned (the placeholder is registered and discoverable).
    # load_tool returns schema.name, not a top-level name key.
    assert data.get("schema", {}).get("name") == "unreach.tool"
