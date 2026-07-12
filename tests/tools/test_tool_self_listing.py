"""Wave W4.5: ``list_registry`` returns registered tool and skill names."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.tools.base import ToolCall
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry


@pytest.mark.asyncio
async def test_list_registry_returns_tool_and_skill_names(tmp_path: Path) -> None:
    executor, tool_set = build_session_registry(
        registry_version=7,
        workspace_root=tmp_path,
    )
    ctx = ToolContext(
        session_id="sess-list",
        workspace_path=tmp_path,
        workspace_id="wid",
        registry_version=tool_set.registry_version,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )
    raw = await executor.dispatch(ctx, ToolCall(name="list_registry", arguments={}))
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    data = envelope["data"]
    assert isinstance(data["tools"], list)
    assert isinstance(data["skills"], list)
    assert "read" in data["tools"]
    assert "log_query" in data["tools"]
    assert "list_registry" not in data["tools"]
    assert "browser" in data["tools"]
    assert data["registry_version"] == tool_set.registry_version
