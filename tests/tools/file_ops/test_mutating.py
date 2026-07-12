"""Mutating file ops tools (`plan/tools-skills-full-inventory-wave-plan.md` Wave 2)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from sevn.tools.base import ToolCall, ToolExecutor
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import tool_from_decorated
from sevn.tools.file_ops.delete import delete_tool
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Minimal workspace tree for mutating file-ops tests."""
    root = tmp_path / "ws"
    root.mkdir()
    (root / "notes.txt").write_text("hello world\n", encoding="utf-8")
    nested = root / "pkg"
    nested.mkdir()
    (nested / "keep.py").write_text("# keep\n", encoding="utf-8")
    return root


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="file-ops-mut-sess",
        workspace_path=workspace,
        workspace_id="file-ops-mut-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        artifact_output_prefix="out/file-ops-mut-sess",
    )


@pytest.fixture
def executor() -> ToolExecutor:
    exe, _tool_set = build_session_registry(registry_version=1)
    return exe


@pytest.mark.asyncio
async def test_mutating_tools_registered(executor: ToolExecutor) -> None:
    names = {definition.name for definition in executor.definitions()}
    assert {
        "write",
        "edit",
        "create_folder",
        "move_file",
        "copy_file",
        "delete",
    } <= names


@pytest.mark.asyncio
async def test_delete_requires_human_ack(executor: ToolExecutor, ctx: ToolContext) -> None:
    blocked = json.loads(
        await executor.dispatch(ctx, ToolCall(name="delete", arguments={"path": "notes.txt"})),
    )
    assert blocked["ok"] is False
    assert blocked["code"] == ToolResultCode.PLAN_HUMAN_GATE

    ctx_ack = replace(ctx, human_acknowledged_tools=frozenset({"delete"}))
    deleted = json.loads(
        await executor.dispatch(ctx_ack, ToolCall(name="delete", arguments={"path": "notes.txt"})),
    )
    assert deleted["ok"] is True
    assert deleted["data"]["deleted"] is True


@pytest.mark.asyncio
async def test_delete_tool_metadata_requires_human_and_not_abortable() -> None:
    definition = tool_from_decorated(delete_tool).definition()
    assert definition.requires_human is True
    assert definition.abortable is False


@pytest.mark.asyncio
async def test_delete_denies_llmignore(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    blocked_path = workspace / ".llmignore" / "blocked" / "secret.txt"
    blocked_path.parent.mkdir(parents=True)
    blocked_path.write_text("hidden", encoding="utf-8")
    ctx_ack = replace(ctx, human_acknowledged_tools=frozenset({"delete"}))
    envelope = json.loads(
        await executor.dispatch(
            ctx_ack,
            ToolCall(name="delete", arguments={"path": ".llmignore/blocked/secret.txt"}),
        ),
    )
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.PERMISSION_DENIED


@pytest.mark.asyncio
async def test_edit_round_trip(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    edit_env = json.loads(
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
    assert edit_env["ok"] is True
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello sevn\n"

    read_env = json.loads(
        await executor.dispatch(ctx, ToolCall(name="read", arguments={"path": "notes.txt"})),
    )
    assert read_env["ok"] is True
    assert "sevn" in read_env["data"]["content"]


@pytest.mark.asyncio
async def test_edit_no_match_error(executor: ToolExecutor, ctx: ToolContext) -> None:
    envelope = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(
                name="edit",
                arguments={
                    "path": "notes.txt",
                    "old_string": "missing-token",
                    "new_string": "x",
                },
            ),
        ),
    )
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.VALIDATION_ERROR
    assert "not found" in envelope["error"].lower()


@pytest.mark.asyncio
async def test_write_and_create_folder_smoke(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    folder_env = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(name="create_folder", arguments={"path": "out/nested"}),
        ),
    )
    assert folder_env["ok"] is True
    assert (workspace / "out" / "file-ops-mut-sess" / "nested").is_dir()

    write_env = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(
                name="write",
                arguments={"path": "out/nested/new.txt", "content": "fresh\n"},
            ),
        ),
    )
    assert write_env["ok"] is True
    assert (workspace / "out" / "file-ops-mut-sess" / "nested" / "new.txt").read_text(
        encoding="utf-8"
    ) == "fresh\n"


@pytest.mark.asyncio
async def test_copy_and_move_file_smoke(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    copy_env = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(
                name="copy_file",
                arguments={"source": "pkg/keep.py", "destination": "pkg/keep_copy.py"},
            ),
        ),
    )
    assert copy_env["ok"] is True
    assert copy_env["data"]["destination"] == "out/file-ops-mut-sess/pkg/keep_copy.py"
    assert (workspace / "out" / "file-ops-mut-sess" / "pkg" / "keep_copy.py").is_file()

    move_env = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(
                name="move_file",
                arguments={
                    "source": "out/file-ops-mut-sess/pkg/keep_copy.py",
                    "destination": "moved.py",
                },
            ),
        ),
    )
    assert move_env["ok"] is True
    assert move_env["data"]["destination"] == "out/file-ops-mut-sess/moved.py"
    assert (workspace / "out" / "file-ops-mut-sess" / "moved.py").is_file()
    assert not (workspace / "pkg" / "keep_copy.py").exists()
