"""``search_in_file`` tool tests (`plan/tools-skills-full-inventory-wave-plan.md` Wave 3)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from sevn.tools.base import ToolCall, ToolExecutor
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.file_ops.search import MAX_SEARCH_MATCHES, _run_ripgrep
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Fixture tree with repeated searchable content."""
    root = tmp_path / "ws"
    root.mkdir()
    src = root / "src"
    src.mkdir()
    (src / "alpha.py").write_text("def alpha():\n    return 'alpha needle'\n", encoding="utf-8")
    (src / "beta.py").write_text("# beta comment\nVALUE = 1\n", encoding="utf-8")
    nested = src / "pkg"
    nested.mkdir()
    (nested / "util.py").write_text("needle in util\n", encoding="utf-8")
    (root / "notes.txt").write_text("plain needle line\n", encoding="utf-8")
    return root


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="search-sess",
        workspace_path=workspace,
        workspace_id="search-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.fixture
def executor() -> ToolExecutor:
    exe, _tool_set = build_session_registry(registry_version=1)
    return exe


def _fake_matches(count: int, *, prefix: str = "src/alpha.py") -> list[dict[str, object]]:
    return [
        {"path": prefix, "line": index + 1, "text": f"needle line {index}"}
        for index in range(count)
    ]


@pytest.fixture
def force_ripgrep_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend ``rg`` exists so tests can stub :func:`_run_ripgrep` only."""
    monkeypatch.setattr("sevn.tools.file_ops.search._find_rg_binary", lambda: "/usr/bin/rg")


@pytest.mark.asyncio
async def test_search_in_file_registered(executor: ToolExecutor) -> None:
    names = {definition.name for definition in executor.definitions()}
    assert "search_in_file" in names


@pytest.mark.asyncio
async def test_search_finds_matches(
    executor: ToolExecutor,
    ctx: ToolContext,
    monkeypatch: pytest.MonkeyPatch,
    force_ripgrep_path: None,
) -> None:
    async def _stub(**_kwargs: Any) -> tuple[list[dict[str, object]], bool, str | None]:
        return (
            [
                {"path": "src/alpha.py", "line": 2, "text": "    return 'alpha needle'"},
                {"path": "notes.txt", "line": 1, "text": "plain needle line"},
            ],
            False,
            None,
        )

    monkeypatch.setattr("sevn.tools.file_ops.search._run_ripgrep", _stub)
    raw = await executor.dispatch(
        ctx,
        ToolCall(name="search_in_file", arguments={"pattern": "needle", "path": "."}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    assert envelope["data"]["count"] == 2
    assert "alpha.py:2:" in envelope["data"]["content"]
    assert envelope["data"]["truncated"] is False


@pytest.mark.asyncio
async def test_search_match_limit_truncated(
    executor: ToolExecutor,
    ctx: ToolContext,
    monkeypatch: pytest.MonkeyPatch,
    force_ripgrep_path: None,
) -> None:
    cap = 3

    async def _stub(**_kwargs: Any) -> tuple[list[dict[str, object]], bool, str | None]:
        return _fake_matches(cap), True, None

    monkeypatch.setattr("sevn.tools.file_ops.search._run_ripgrep", _stub)
    raw = await executor.dispatch(
        ctx,
        ToolCall(
            name="search_in_file",
            arguments={"pattern": "needle", "path": "src", "include": "**/*.py"},
        ),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    assert envelope["data"]["count"] == cap
    assert envelope["data"]["truncated"] is True
    assert envelope["data"]["include"] == "**/*.py"


@pytest.mark.asyncio
async def test_search_denies_llmignore(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    blocked = workspace / ".llmignore" / "blocked" / "secret.txt"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("needle", encoding="utf-8")
    raw = await executor.dispatch(
        ctx,
        ToolCall(
            name="search_in_file",
            arguments={"pattern": "needle", "path": ".llmignore/blocked/secret.txt"},
        ),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.PERMISSION_DENIED


@pytest.mark.asyncio
async def test_search_denies_escape_root(
    executor: ToolExecutor,
    ctx: ToolContext,
) -> None:
    raw = await executor.dispatch(
        ctx,
        ToolCall(name="search_in_file", arguments={"pattern": "x", "path": "../outside"}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.VALIDATION_ERROR


@pytest.mark.asyncio
async def test_large_search_spills_to_disk(
    executor: ToolExecutor,
    ctx: ToolContext,
    monkeypatch: pytest.MonkeyPatch,
    force_ripgrep_path: None,
) -> None:
    async def _stub(**_kwargs: Any) -> tuple[list[dict[str, object]], bool, str | None]:
        # Exceed TOOL_LARGE_RESULT_THRESHOLD_BYTES (32 KiB) so dispatch spills to disk.
        return _fake_matches(1500, prefix="src/alpha.py"), False, None

    monkeypatch.setattr("sevn.tools.file_ops.search._run_ripgrep", _stub)
    raw = await executor.dispatch(
        ctx,
        ToolCall(name="search_in_file", arguments={"pattern": "needle", "path": "."}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    data = envelope["data"]
    assert {"spill_path", "summary", "size"}.issubset(data.keys())
    assert "spill_notice" in data
    spill_path = ctx.workspace_path / data["spill_path"]
    assert spill_path.is_file()
    assert spill_path.stat().st_size > 2000


@pytest.mark.asyncio
async def test_search_empty_pattern_rejected(
    executor: ToolExecutor,
    ctx: ToolContext,
) -> None:
    raw = await executor.dispatch(
        ctx,
        ToolCall(name="search_in_file", arguments={"pattern": "   ", "path": "."}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.VALIDATION_ERROR


@pytest.mark.asyncio
async def test_search_python_fallback_when_rg_missing(
    executor: ToolExecutor,
    ctx: ToolContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loguru import logger as loguru_logger

    monkeypatch.setattr("sevn.tools.file_ops.search._find_rg_binary", lambda: None)
    monkeypatch.setattr("sevn.tools.file_ops.search._python_fallback_logged", False)
    captured: list[str] = []
    sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="WARNING")
    try:
        raw = await executor.dispatch(
            ctx,
            ToolCall(name="search_in_file", arguments={"pattern": "needle", "path": "."}),
        )
    finally:
        loguru_logger.remove(sink_id)
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    assert envelope["data"]["engine"] == "python"
    assert envelope["data"]["count"] >= 1
    assert any("search_in_file_no_ripgrep_using_python_fallback" in line for line in captured)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_integration_with_rg(
    workspace: Path,
    ctx: ToolContext,
) -> None:
    if shutil.which("rg") is None:
        pytest.skip("ripgrep (rg) not installed")

    matches, truncated, error = await _run_ripgrep(
        workspace=workspace,
        pattern="needle",
        search_path=workspace,
        include_glob="**/*.py",
        max_matches=MAX_SEARCH_MATCHES,
    )
    assert error is None
    assert truncated is False
    paths = {str(row["path"]) for row in matches}
    assert "src/alpha.py" in paths
    assert "src/pkg/util.py" in paths
