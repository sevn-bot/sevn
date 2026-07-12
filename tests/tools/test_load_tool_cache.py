"""Per-turn ``load_tool`` memoisation tests (reactive-plum Wave 5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.tools.base import ToolCall
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        session_id="load-tool-cache",
        workspace_path=tmp_path,
        workspace_id="wid",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.mark.asyncio
async def test_load_tool_second_call_returns_cached_envelope(ctx: ToolContext) -> None:
    from loguru import logger as loguru_logger

    exe, _ = build_session_registry(registry_version=1)
    call = ToolCall(name="load_tool", arguments={"name": "read"})
    first = json.loads(await exe.dispatch(ctx, call))
    assert first["ok"] is True
    assert "schema" in first["data"]

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="DEBUG")
    try:
        second_raw = await exe.dispatch(ctx, call)
    finally:
        loguru_logger.remove(sink_id)
    second = json.loads(second_raw)
    assert second == first
    assert ctx.loaded_tools["read"] == second_raw
    assert any("tool_call.cached" in line for line in captured)


@pytest.mark.asyncio
async def test_load_tool_cache_is_per_context(tmp_path: Path) -> None:
    exe, _ = build_session_registry(registry_version=1)
    ctx_a = ToolContext(
        session_id="a",
        workspace_path=tmp_path,
        workspace_id="w",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )
    ctx_b = ToolContext(
        session_id="b",
        workspace_path=tmp_path,
        workspace_id="w",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )
    call = ToolCall(name="load_tool", arguments={"name": "read"})
    await exe.dispatch(ctx_a, call)
    assert "read" in ctx_a.loaded_tools
    assert ctx_b.loaded_tools == {}
