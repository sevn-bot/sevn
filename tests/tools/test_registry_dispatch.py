"""Wave T contract tests: ``integration_call`` / ``sandbox_exec`` / MCP stdio dispatch.

Asserts the registry honors :class:`sevn.tools.runtime_dispatch.RuntimeToolBindings`
hooks per ``specs/11-tools-registry.md`` §10.1 — that ``_disabled_gated_tool_executor`` and
:class:`sevn.tools.registry.McpUnavailableTool` are unreachable when live runtime
clients are injected, and that injected client errors surface as compliant §3.1
envelopes (``MCP_UNAVAILABLE`` / ``INTERNAL_ERROR``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from sevn.tools.base import ToolCall
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import McpUnavailableTool, build_session_registry
from sevn.tools.runtime_dispatch import (
    McpStdioTool,
    RuntimeToolBindings,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    return workspace_dir


@pytest.fixture
def exec_ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="sess",
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=99,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


class _FakeIntegrationProxy:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def integration_call(
        self,
        *,
        service: str,
        method: str,
        args: Mapping[str, Any],
        ctx: ToolContext,
    ) -> Mapping[str, Any]:
        self.calls.append(
            {"service": service, "method": method, "args": dict(args), "ctx": ctx.session_id},
        )
        return {"service": service, "method": method, "result": dict(args)}


class _FailingIntegrationProxy:
    async def integration_call(
        self,
        *,
        service: str,
        method: str,
        args: Mapping[str, Any],
        ctx: ToolContext,
    ) -> Mapping[str, Any]:
        _ = (service, method, args, ctx)
        raise RuntimeError("upstream 503")


class _FakeSandbox:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def sandbox_exec(
        self,
        *,
        language: str,
        code: str,
        ctx: ToolContext,
    ) -> Mapping[str, Any]:
        self.calls.append({"language": language, "code": code, "ctx": ctx.session_id})
        return {"exit_code": 0, "stdout": f"ran {language}", "stderr": ""}


class _FakeMcpClient:
    def __init__(self, payload: Mapping[str, Any] | None = None) -> None:
        self.payload = dict(payload or {"ok": True})
        self.calls: list[dict[str, Any]] = []

    async def call_tool(
        self,
        *,
        server_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        ctx: ToolContext,
    ) -> Mapping[str, Any]:
        self.calls.append(
            {
                "server_id": server_id,
                "tool_name": tool_name,
                "arguments": dict(arguments),
                "ctx": ctx.session_id,
            },
        )
        return dict(self.payload)


class _FailingMcpClient:
    async def call_tool(
        self,
        *,
        server_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        ctx: ToolContext,
    ) -> Mapping[str, Any]:
        _ = (server_id, tool_name, arguments, ctx)
        raise OSError("stdio pipe closed")


@pytest.mark.asyncio
async def test_integration_call_dispatches_via_runtime_bindings(
    exec_ctx: ToolContext,
) -> None:
    proxy = _FakeIntegrationProxy()
    executor, _ts = build_session_registry(
        registry_version=exec_ctx.registry_version,
        runtime_bindings=RuntimeToolBindings(integration=proxy),
    )

    definition = executor.get("integration_call").definition()  # type: ignore[union-attr]
    assert definition.enabled is True

    envelope = json.loads(
        await executor.dispatch(
            exec_ctx,
            ToolCall(
                name="integration_call",
                arguments={"service": "github", "method": "repos.get", "args": {"owner": "x"}},
            ),
        ),
    )

    assert envelope["ok"] is True
    assert envelope["data"]["service"] == "github"
    assert envelope["data"]["method"] == "repos.get"
    assert envelope["data"]["result"] == {"owner": "x"}
    assert proxy.calls
    assert proxy.calls[0]["service"] == "github"


@pytest.mark.asyncio
async def test_integration_call_disabled_without_runtime_bindings(
    exec_ctx: ToolContext,
) -> None:
    executor, _ts = build_session_registry(registry_version=exec_ctx.registry_version)
    envelope = json.loads(
        await executor.dispatch(
            exec_ctx,
            ToolCall(
                name="integration_call",
                arguments={"service": "x", "method": "y", "args": {}},
            ),
        ),
    )
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.DISABLED_TOOL


@pytest.mark.asyncio
async def test_integration_call_envelopes_runtime_errors(
    exec_ctx: ToolContext,
) -> None:
    executor, _ts = build_session_registry(
        registry_version=exec_ctx.registry_version,
        runtime_bindings=RuntimeToolBindings(integration=_FailingIntegrationProxy()),
    )

    envelope = json.loads(
        await executor.dispatch(
            exec_ctx,
            ToolCall(
                name="integration_call",
                arguments={"service": "s", "method": "m", "args": {}},
            ),
        ),
    )
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.INTERNAL_ERROR
    assert "upstream 503" in envelope["error"]


@pytest.mark.asyncio
async def test_sandbox_exec_dispatches_via_runtime_bindings(
    exec_ctx: ToolContext,
) -> None:
    sandbox = _FakeSandbox()
    executor, _ts = build_session_registry(
        registry_version=exec_ctx.registry_version,
        runtime_bindings=RuntimeToolBindings(sandbox=sandbox),
    )

    definition = executor.get("sandbox_exec").definition()  # type: ignore[union-attr]
    assert definition.enabled is True
    assert definition.sandbox_mode == "docker"

    envelope = json.loads(
        await executor.dispatch(
            exec_ctx,
            ToolCall(
                name="sandbox_exec",
                arguments={"language": "python", "code": "print(1)"},
            ),
        ),
    )
    assert envelope["ok"] is True
    assert envelope["data"]["exit_code"] == 0
    assert envelope["data"]["stdout"] == "ran python"
    assert sandbox.calls
    assert sandbox.calls[0]["language"] == "python"


@pytest.mark.asyncio
async def test_sandbox_exec_disabled_without_runtime_bindings(
    exec_ctx: ToolContext,
) -> None:
    executor, _ts = build_session_registry(registry_version=exec_ctx.registry_version)
    envelope = json.loads(
        await executor.dispatch(
            exec_ctx,
            ToolCall(
                name="sandbox_exec",
                arguments={"language": "python", "code": "1"},
            ),
        ),
    )
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.DISABLED_TOOL


@pytest.mark.asyncio
async def test_mcp_stdio_dispatches_to_client(exec_ctx: ToolContext) -> None:
    from sevn.tools.base import ToolDefinition

    descriptor = ToolDefinition(
        name="code_review_graph.get_minimal_context_tool",
        category="mcp",
        description="recorded mcp",
        parameters={"type": "object", "properties": {}},
        enabled=True,
    )
    payload = {"path": "src/sevn/foo.py", "snippets": ["chunk-1"]}
    mcp_client = _FakeMcpClient(payload=payload)

    executor, _ts = build_session_registry(
        registry_version=exec_ctx.registry_version,
        extra_mcp=(descriptor,),
        runtime_bindings=RuntimeToolBindings(
            mcp=mcp_client,
            mcp_servers={"code_review_graph": {"command": "code-review-graph", "args": ["serve"]}},
        ),
    )

    registered = executor.get(descriptor.name)
    assert isinstance(registered, McpStdioTool)
    assert not isinstance(registered, McpUnavailableTool)

    envelope = json.loads(
        await executor.dispatch(
            exec_ctx,
            ToolCall(name=descriptor.name, arguments={"query": "Foo"}),
        ),
    )

    assert envelope["ok"] is True
    assert envelope["data"] == payload
    assert mcp_client.calls
    assert mcp_client.calls[0]["server_id"] == "code_review_graph"
    assert mcp_client.calls[0]["tool_name"] == "get_minimal_context_tool"
    assert mcp_client.calls[0]["arguments"] == {"query": "Foo"}


@pytest.mark.asyncio
async def test_mcp_stdio_falls_back_when_client_errors(exec_ctx: ToolContext) -> None:
    from sevn.tools.base import ToolDefinition

    descriptor = ToolDefinition(
        name="code_review_graph.broken_tool",
        category="mcp",
        description="recorded mcp",
        parameters={"type": "object", "properties": {}},
        enabled=True,
    )
    executor, _ts = build_session_registry(
        registry_version=exec_ctx.registry_version,
        extra_mcp=(descriptor,),
        runtime_bindings=RuntimeToolBindings(
            mcp=_FailingMcpClient(),
            mcp_servers={"code_review_graph": {"command": "code-review-graph", "args": ["serve"]}},
        ),
    )

    envelope = json.loads(
        await executor.dispatch(
            exec_ctx,
            ToolCall(name=descriptor.name, arguments={}),
        ),
    )
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.MCP_UNAVAILABLE
    assert envelope["data"]["server_id"] == "code_review_graph"


@pytest.mark.asyncio
async def test_mcp_stdio_falls_back_to_unavailable_for_unknown_server(
    exec_ctx: ToolContext,
) -> None:
    from sevn.tools.base import ToolDefinition

    descriptor = ToolDefinition(
        name="other_server.tool",
        category="mcp",
        description="not registered as live",
        parameters={"type": "object", "properties": {}},
        enabled=True,
    )
    executor, _ts = build_session_registry(
        registry_version=exec_ctx.registry_version,
        extra_mcp=(descriptor,),
        runtime_bindings=RuntimeToolBindings(
            mcp=_FakeMcpClient(),
            mcp_servers={"code_review_graph": {"command": "code-review-graph", "args": ["serve"]}},
        ),
    )

    registered = executor.get(descriptor.name)
    assert isinstance(registered, McpUnavailableTool)

    envelope = json.loads(
        await executor.dispatch(
            exec_ctx,
            ToolCall(name=descriptor.name, arguments={}),
        ),
    )
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.MCP_UNAVAILABLE
