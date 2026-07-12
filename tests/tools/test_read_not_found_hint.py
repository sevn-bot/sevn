"""``read`` tool not-found envelope hint (reactive-plum Wave 2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.tools.base import ToolCall, ToolExecutor
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="read-hint-sess",
        workspace_path=workspace,
        workspace_id="read-hint-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.fixture
def executor() -> ToolExecutor:
    exe, _tool_set = build_session_registry(registry_version=1)
    return exe


@pytest.mark.asyncio
async def test_read_not_found_envelope_carries_do_not_reconstruct_hint(
    ctx: ToolContext,
    executor: ToolExecutor,
) -> None:
    raw = await executor.dispatch(
        ctx,
        ToolCall(name="read", arguments={"path": "missing/file.md"}),
    )
    payload = json.loads(raw)
    assert payload["ok"] is False
    assert payload["code"] == ToolResultCode.VALIDATION_ERROR
    assert payload["data"]["path"] == "missing/file.md"
    assert payload["data"]["error"] == "not_found"
    assert payload["data"]["hint"] == "do_not_reconstruct"
