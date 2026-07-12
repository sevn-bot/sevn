"""``load_tool`` readiness ``action`` advice for not-ready tools with ready fallbacks."""

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
        session_id="load-tool-readiness",
        workspace_path=tmp_path,
        workspace_id="wid",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.mark.asyncio
async def test_load_tool_not_ready_advises_ready_fallback(ctx: ToolContext) -> None:
    """web_search (needs_key) with ready serp fallback carries an imperative action."""
    exe, _tool_set = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="load_tool", arguments={"name": "web_search"}),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    readiness = env["data"]["readiness"]
    assert readiness["status"] == "needs_key"
    assert readiness["fallback_tool"] == "serp"
    assert "`serp`" in readiness["action"]


@pytest.mark.asyncio
async def test_load_tool_ready_tool_has_no_action(ctx: ToolContext) -> None:
    """A ready tool's readiness row carries no fallback action."""
    exe, _tool_set = build_session_registry(registry_version=1)
    raw = await exe.dispatch(ctx, ToolCall(name="load_tool", arguments={"name": "serp"}))
    env = json.loads(raw)
    assert env["ok"] is True
    readiness = env["data"]["readiness"]
    assert readiness["status"] == "ready"
    assert "action" not in readiness
