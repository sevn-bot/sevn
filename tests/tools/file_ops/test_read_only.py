"""Read-only file ops tools (`plan/tools-skills-full-inventory-wave-plan.md` Wave 1)."""

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
    """Minimal workspace tree for file-ops tests."""
    root = tmp_path / "ws"
    root.mkdir()
    (root / "hello.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    src = root / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hi')\n", encoding="utf-8")
    pkg = src / "pkg"
    pkg.mkdir()
    (pkg / "util.py").write_text("# util\n", encoding="utf-8")
    return root


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="file-ops-sess",
        workspace_path=workspace,
        workspace_id="file-ops-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.fixture
def executor() -> ToolExecutor:
    exe, _tool_set = build_session_registry(registry_version=1)
    return exe


@pytest.mark.asyncio
async def test_read_only_tools_registered(executor: ToolExecutor) -> None:
    names = {definition.name for definition in executor.definitions()}
    assert {"read", "list_dir", "glob", "find_file", "file_info"} <= names


@pytest.mark.asyncio
async def test_read_returns_line_numbers(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    raw = await executor.dispatch(
        ctx,
        ToolCall(name="read", arguments={"path": "hello.txt"}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    assert envelope["data"]["content"].startswith("1|alpha")
    assert "2|beta" in envelope["data"]["content"]


@pytest.mark.asyncio
async def test_read_directory_listing(
    executor: ToolExecutor,
    ctx: ToolContext,
) -> None:
    raw = await executor.dispatch(ctx, ToolCall(name="read", arguments={"path": "src"}))
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    assert envelope["data"]["kind"] == "directory"
    assert "main.py" in envelope["data"]["content"]


@pytest.mark.asyncio
async def test_read_denies_llmignore(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    blocked = workspace / ".llmignore" / "blocked" / "secret.txt"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("hidden", encoding="utf-8")
    raw = await executor.dispatch(
        ctx,
        ToolCall(name="read", arguments={"path": ".llmignore/blocked/secret.txt"}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.PERMISSION_DENIED


@pytest.mark.asyncio
async def test_read_denies_escape_root(
    executor: ToolExecutor,
    ctx: ToolContext,
) -> None:
    raw = await executor.dispatch(
        ctx,
        ToolCall(name="read", arguments={"path": "../outside.txt"}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.VALIDATION_ERROR


@pytest.mark.asyncio
async def test_list_dir_hides_llmignore_entries(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    (workspace / ".llmignore").mkdir()
    (workspace / ".llmignore" / "blocked").mkdir(parents=True)
    (workspace / "visible.txt").write_text("ok", encoding="utf-8")
    raw = await executor.dispatch(ctx, ToolCall(name="list_dir", arguments={"path": "."}))
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    names = {entry["name"] for entry in envelope["data"]["entries"]}
    assert "visible.txt" in names
    assert ".llmignore" not in names


@pytest.mark.asyncio
async def test_large_read_spills_to_disk(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    # One long single line (no newlines) so paging cannot kick in and the read
    # exceeds the inline threshold, forcing a spill descriptor.
    (workspace / "big.txt").write_text("z" * 50_000, encoding="utf-8")
    raw = await executor.dispatch(ctx, ToolCall(name="read", arguments={"path": "big.txt"}))
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    data = envelope["data"]
    assert {"spill_path", "summary", "size"}.issubset(data.keys())
    assert "spill_notice" in data
    assert data["spill_depth"] == 1
    spill_path = workspace / data["spill_path"]
    assert spill_path.is_file()
    assert spill_path.stat().st_size > 2000


@pytest.mark.asyncio
async def test_glob_and_read_smoke(
    executor: ToolExecutor,
    ctx: ToolContext,
) -> None:
    """Tier-B-style smoke: registry ``glob`` then ``read`` on a matched path."""
    glob_raw = await executor.dispatch(
        ctx,
        ToolCall(name="glob", arguments={"pattern": "**/*.py", "path": "src"}),
    )
    glob_env = json.loads(glob_raw)
    assert glob_env["ok"] is True
    assert glob_env["data"]["count"] >= 1
    target = glob_env["data"]["paths"][0]
    read_raw = await executor.dispatch(ctx, ToolCall(name="read", arguments={"path": target}))
    read_env = json.loads(read_raw)
    assert read_env["ok"] is True
    assert read_env["data"]["kind"] == "file"


@pytest.mark.asyncio
async def test_find_file_partial_match(
    executor: ToolExecutor,
    ctx: ToolContext,
) -> None:
    raw = await executor.dispatch(
        ctx,
        ToolCall(name="find_file", arguments={"name": "main", "path": "src"}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    assert any("main.py" in hit for hit in envelope["data"]["paths"])


@pytest.mark.asyncio
async def test_file_info_reports_metadata(
    executor: ToolExecutor,
    ctx: ToolContext,
) -> None:
    raw = await executor.dispatch(
        ctx,
        ToolCall(name="file_info", arguments={"path": "hello.txt"}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    assert envelope["data"]["type"] == "file"
    assert envelope["data"]["size"] > 0
    assert "mtime" in envelope["data"]


@pytest.mark.asyncio
async def test_read_source_code_mirror_via_workspace_path(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    """Mirrored source under ``source_code/`` reads via a normal workspace path."""
    mirror = workspace / "source_code" / "src" / "sevn" / "gateway"
    mirror.mkdir(parents=True)
    (mirror / "agent_turn.py").write_text("# mirrored source\n", encoding="utf-8")
    raw = await executor.dispatch(
        ctx,
        ToolCall(
            name="read",
            arguments={"path": "source_code/src/sevn/gateway/agent_turn.py"},
        ),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    assert envelope["data"]["kind"] == "file"
    assert envelope["data"]["path"] == "source_code/src/sevn/gateway/agent_turn.py"
    assert "mirrored source" in envelope["data"]["content"]
