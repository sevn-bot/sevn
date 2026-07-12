"""Memory K/V tools (`plan/tools-skills-full-inventory-wave-plan.md` Wave 4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.storage.sqlite import open_sevn_sqlite
from sevn.tools.base import ToolCall, ToolExecutor
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Workspace with migrated ``sevn.db`` under ``.sevn``."""
    root = tmp_path / "ws"
    root.mkdir()
    conn = open_sevn_sqlite(root / ".sevn")
    conn.close()
    return root


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="memory-sess",
        workspace_path=workspace,
        workspace_id="memory-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.fixture
def executor() -> ToolExecutor:
    exe, _tool_set = build_session_registry(registry_version=1)
    return exe


@pytest.mark.asyncio
async def test_memory_tools_registered(executor: ToolExecutor) -> None:
    names = {definition.name for definition in executor.definitions()}
    assert {"memory_get", "memory_store", "memory_search"} <= names


@pytest.mark.asyncio
async def test_memory_store_get_round_trip(
    executor: ToolExecutor,
    ctx: ToolContext,
) -> None:
    store_raw = await executor.dispatch(
        ctx,
        ToolCall(
            name="memory_store",
            arguments={"key": "prefs", "content": "dark mode", "tags": "ui"},
        ),
    )
    store_env = json.loads(store_raw)
    assert store_env["ok"] is True
    assert store_env["data"]["key"] == "prefs"

    get_raw = await executor.dispatch(
        ctx,
        ToolCall(name="memory_get", arguments={"key": "prefs"}),
    )
    get_env = json.loads(get_raw)
    assert get_env["ok"] is True
    assert get_env["data"]["content"] == "dark mode"
    assert get_env["data"]["tags"] == "ui"


@pytest.mark.asyncio
async def test_memory_search_hits_daily_log(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    mem_dir = workspace / "memory"
    mem_dir.mkdir()
    (mem_dir / "2026-05-22.md").write_text(
        "Morning standup\nDiscussed deployment timeline\n",
        encoding="utf-8",
    )

    raw = await executor.dispatch(
        ctx,
        ToolCall(
            name="memory_search",
            arguments={"query": "deployment", "source": "daily_log", "limit": 5},
        ),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    hits = envelope["data"]["hits"]
    assert len(hits) == 1
    assert hits[0]["source"] == "daily_log"
    assert "deployment" in hits[0]["content"].lower()


@pytest.mark.asyncio
async def test_memory_search_empty_query_browses_recent(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    """Empty query browses recent entries instead of erroring (recall path)."""
    mem_dir = workspace / "memory"
    mem_dir.mkdir()
    (mem_dir / "2026-05-22.md").write_text(
        "Morning standup\nDiscussed deployment timeline\n",
        encoding="utf-8",
    )

    raw = await executor.dispatch(
        ctx,
        ToolCall(name="memory_search", arguments={"source": "daily_log", "limit": 5}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    assert len(envelope["data"]["hits"]) >= 1
