"""Native tool artifact output confinement (`live-session-2026-06-05` P10)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.tools.base import ToolCall, ToolExecutor
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry
from sevn.tools.workspace_files import write_workspace_md


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "notes.txt").write_text("hello world\n", encoding="utf-8")
    return root


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="artifact-sess",
        workspace_path=workspace,
        workspace_id="artifact-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        artifact_output_prefix="out/artifact-sess",
    )


@pytest.fixture
def executor() -> ToolExecutor:
    exe, _tool_set = build_session_registry(registry_version=1)
    return exe


@pytest.mark.asyncio
async def test_write_rebases_bare_path_into_output_dir(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    envelope = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(name="write", arguments={"path": "report.pdf", "content": "%PDF\n"}),
        ),
    )
    assert envelope["ok"] is True
    assert envelope["data"]["path"] == "out/artifact-sess/report.pdf"
    assert (workspace / "out" / "artifact-sess" / "report.pdf").is_file()


@pytest.mark.asyncio
async def test_write_rejects_structured_root_file_via_write_tool(
    executor: ToolExecutor,
    ctx: ToolContext,
) -> None:
    envelope = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(name="write", arguments={"path": "SOUL.md", "content": "# soul\n"}),
        ),
    )
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.VALIDATION_ERROR


def test_write_workspace_md_still_writes_soul_md(workspace: Path) -> None:
    written = write_workspace_md(workspace, "SOUL.md", "# soul\n")
    assert written.name == "SOUL.md"
    assert (workspace / "SOUL.md").read_text(encoding="utf-8") == "# soul\n"


@pytest.mark.asyncio
async def test_edit_existing_root_file_still_allowed(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    envelope = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(
                name="edit",
                arguments={
                    "path": "notes.txt",
                    "old_string": "world",
                    "new_string": "sevn",
                },
            ),
        ),
    )
    assert envelope["ok"] is True
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello sevn\n"


@pytest.mark.asyncio
async def test_move_destination_rebased_under_output_dir(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    src = workspace / "notes.txt"
    envelope = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(
                name="move_file",
                arguments={"source": "notes.txt", "destination": "moved.txt"},
            ),
        ),
    )
    assert envelope["ok"] is True
    assert envelope["data"]["destination"] == "out/artifact-sess/moved.txt"
    assert (workspace / "out" / "artifact-sess" / "moved.txt").is_file()
    assert not src.exists()
