"""Batch F W27 RED: MCP ``mcp__server__tool`` naming (#90) and per-profile enablement (→ W29)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.tools.mcp_stdio_client import list_tools_from_server
from sevn.tools.runtime_dispatch import _server_id_for_tool


def _fake_mcp_list_tools(*, tool_name: str = "ping") -> Any:
    """Build minimal MCP list_tools result for naming tests."""
    tool = MagicMock()
    tool.name = tool_name
    tool.description = "demo tool"
    tool.inputSchema = {"type": "object", "properties": {}}
    result = MagicMock()
    result.tools = [tool]
    return result


@pytest.mark.asyncio
async def test_list_tools_from_server_uses_mcp_double_underscore_convention() -> None:
    """Registered MCP tools use ``mcp__<server>__<tool>`` qualified names."""
    fake_session = AsyncMock()
    fake_session.initialize = AsyncMock()
    fake_session.list_tools = AsyncMock(return_value=_fake_mcp_list_tools(tool_name="ping"))
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)

    fake_streams = (AsyncMock(), AsyncMock())

    def _fake_stdio_client(_params: Any) -> Any:
        class _CM:
            async def __aenter__(self_cm) -> Any:
                return fake_streams

            async def __aexit__(self_cm, *args: Any) -> bool:
                return False

        return _CM()

    with (
        patch("sevn.tools.mcp_stdio_client.stdio_client", side_effect=_fake_stdio_client),
        patch("sevn.tools.mcp_stdio_client.ClientSession", return_value=fake_session),
    ):
        tools = await list_tools_from_server("demo", "echo", [], timeout_s=1.0)

    assert len(tools) == 1
    assert tools[0].name == "mcp__demo__ping"


def test_server_id_for_tool_parses_mcp_double_underscore_qualified_name() -> None:
    """Runtime dispatch extracts the server id from ``mcp__server__tool`` names."""
    qualified = "mcp__code_review_graph__get_minimal_context_tool"
    assert _server_id_for_tool(qualified) == "code_review_graph"


def test_format_mcp_tool_name_matches_convention() -> None:
    """Public formatter emits stable ``mcp__server__tool`` identifiers."""
    from sevn.tools.mcp_naming import format_mcp_tool_name

    assert format_mcp_tool_name("graphify", "query") == "mcp__graphify__query"


def test_routing_profile_can_disable_mcp_server() -> None:
    """A routing profile may disable an MCP server even when workspace enables it."""
    from sevn.tools.mcp_profile_policy import resolve_mcp_servers_for_profile

    workspace = WorkspaceConfig.minimal()
    workspace.mcp_enabled = ["graphify", "code_review_graph"]
    workspace.routing_profiles = {
        "locked-down": {
            "mcp_disabled_servers": ["code_review_graph"],
        }
    }
    effective = resolve_mcp_servers_for_profile(
        workspace,
        profile_id="locked-down",
        declared_servers={
            "graphify": {"command": "graphify", "args": ["serve"]},
            "code_review_graph": {"command": "crg", "args": ["serve"]},
        },
    )
    assert "graphify" in effective
    assert "code_review_graph" not in effective


def test_resolve_mcp_servers_for_profile_honours_workspace_mcp_enabled() -> None:
    """When a profile does not override MCP, workspace ``mcp_enabled`` applies."""
    from sevn.tools.mcp_profile_policy import resolve_mcp_servers_for_profile

    workspace = WorkspaceConfig.minimal()
    workspace.mcp_enabled = ["graphify"]
    declared = {
        "graphify": {"command": "graphify", "args": ["serve"]},
        "other": {"command": "other", "args": []},
    }
    effective = resolve_mcp_servers_for_profile(
        workspace,
        profile_id=None,
        declared_servers=declared,
    )
    assert set(effective) == {"graphify"}
