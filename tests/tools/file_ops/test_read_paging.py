"""Paging tests for the ``read`` tool (Wave W1).

A file whose numbered output exceeds the inline byte threshold pages to a default
window and exposes a ``next_offset`` cursor; small files do not.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.tools.base import ToolCall, ToolExecutor
from sevn.tools.context import ToolContext
from sevn.tools.file_ops.read import DEFAULT_READ_PAGE_LINES
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
        session_id="read-paging-sess",
        workspace_path=workspace,
        workspace_id="read-paging-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.fixture
def executor() -> ToolExecutor:
    exe, _tool_set = build_session_registry(registry_version=1)
    return exe


def _write_many_lines(workspace: Path, name: str, count: int) -> None:
    # Each line is wide enough that one default page clears the inline threshold.
    body = "\n".join(f"line-{index:05d}-{'x' * 60}" for index in range(count))
    (workspace / name).write_text(body + "\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_long_file_returns_next_offset(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    # Wide lines force paging; the returned page must stay inline (not spill).
    total = 600
    _write_many_lines(workspace, "long.txt", total)
    raw = await executor.dispatch(ctx, ToolCall(name="read", arguments={"path": "long.txt"}))
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    data = envelope["data"]
    assert "spill_path" not in data
    assert data["total_lines"] == total
    assert 0 < data["line_count"] <= DEFAULT_READ_PAGE_LINES
    assert data["next_offset"] == data["line_count"] + 1


@pytest.mark.asyncio
async def test_next_offset_continues_to_next_slice(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    total = 600
    _write_many_lines(workspace, "long.txt", total)
    first = json.loads(
        await executor.dispatch(ctx, ToolCall(name="read", arguments={"path": "long.txt"}))
    )["data"]
    assert "spill_path" not in first
    next_offset = first["next_offset"]

    second = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(name="read", arguments={"path": "long.txt", "offset": next_offset}),
        )
    )["data"]
    assert "spill_path" not in second
    assert second["total_lines"] == total
    # Remaining lines fit inline, so this last page has no further cursor.
    assert "next_offset" not in second
    assert second["content"].startswith(f"{next_offset}|line-{next_offset - 1:05d}")
    assert second["line_count"] == total - (next_offset - 1)


@pytest.mark.asyncio
async def test_small_file_has_no_next_offset(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    (workspace / "small.txt").write_text("a\nb\nc\n", encoding="utf-8")
    data = json.loads(
        await executor.dispatch(ctx, ToolCall(name="read", arguments={"path": "small.txt"}))
    )["data"]
    assert data["total_lines"] == 3
    assert "next_offset" not in data
