"""Tests for Python docstring/symbol file-op tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.tools.base import ToolCall, ToolExecutor
from sevn.tools.context import ToolContext
from sevn.tools.decorator import tool_from_decorated
from sevn.tools.file_ops.docstrings import (
    get_module_docstring_tool,
    get_symbol_docstring_tool,
    list_symbols_tool,
)
from sevn.tools.permissions import AllowAllPermissionPolicy


def _ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="s",
        workspace_path=workspace,
        workspace_id="w",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.mark.asyncio
async def test_docstring_tools_return_expected_payload(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        '"""Module docs."""\n\n'
        "class Demo:\n"
        '    """Demo docs."""\n'
        "    pass\n\n"
        "def run() -> None:\n"
        '    """Run docs."""\n'
        "    return None\n",
        encoding="utf-8",
    )
    exe = ToolExecutor(default_timeout_seconds=None)
    exe.register(tool_from_decorated(get_module_docstring_tool))
    exe.register(tool_from_decorated(get_symbol_docstring_tool))
    exe.register(tool_from_decorated(list_symbols_tool))
    ctx = _ctx(tmp_path)

    module_env = json.loads(
        await exe.dispatch(
            ctx,
            ToolCall(name="get_module_docstring", arguments={"path": "sample.py"}),
        )
    )
    assert module_env["ok"] is True
    assert module_env["data"]["docstring"] == "Module docs."

    symbol_env = json.loads(
        await exe.dispatch(
            ctx,
            ToolCall(
                name="get_symbol_docstring",
                arguments={"path": "sample.py", "symbol": "Demo"},
            ),
        )
    )
    assert symbol_env["ok"] is True
    assert symbol_env["data"]["docstring"] == "Demo docs."

    list_env = json.loads(
        await exe.dispatch(
            ctx,
            ToolCall(name="list_symbols", arguments={"path": "sample.py"}),
        )
    )
    assert list_env["ok"] is True
    names = [row["name"] for row in list_env["data"]["symbols"]]
    assert names == ["Demo", "run"]
