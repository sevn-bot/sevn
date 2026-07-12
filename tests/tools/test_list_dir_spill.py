"""``list_dir`` spill sentinel tests (reactive-plum Wave 5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.tools.base import ToolCall
from sevn.tools.context import ToolContext
from sevn.tools.file_ops.list_glob import MAX_LISTING_RESULTS
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    root = tmp_path / "ws"
    root.mkdir()
    target = root / "many"
    target.mkdir()
    for index in range(MAX_LISTING_RESULTS + 25):
        (target / f"file-{index:04d}.txt").write_text("x", encoding="utf-8")
    return ToolContext(
        session_id="list-dir-spill",
        workspace_path=root,
        workspace_id="wid",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.mark.asyncio
async def test_list_dir_truncates_and_spills(ctx: ToolContext) -> None:
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(ctx, ToolCall(name="list_dir", arguments={"path": "many"}))
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    data = envelope["data"]
    total = MAX_LISTING_RESULTS + 25
    assert data["count"] == total
    assert data["shown"] == MAX_LISTING_RESULTS
    assert data["truncated"] is True
    assert isinstance(data["spill_path"], str)
    assert "spill" in data["spill_notice"]
    assert "summary" in data
    assert data["summary"]["files"] == total
    assert data["summary"]["folders"] == 0
    assert "entries" not in data

    spill_file = ctx.workspace_path / data["spill_path"]
    assert spill_file.is_file()
    spill_payload = json.loads(spill_file.read_text(encoding="utf-8"))
    assert len(spill_payload["entries"]) == total


@pytest.mark.asyncio
async def test_list_dir_small_directory_has_no_spill(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a.txt").write_text("x", encoding="utf-8")
    ctx = ToolContext(
        session_id="list-dir-small",
        workspace_path=root,
        workspace_id="wid",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(ctx, ToolCall(name="list_dir", arguments={"path": "."}))
    data = json.loads(raw)["data"]
    assert data["count"] == 1
    assert data["truncated"] is False
    assert "spill_path" not in data
