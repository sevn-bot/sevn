"""W5 — stub schema UX: auto-grant on validation error + minimal stub params (msg=4f8208)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.tools import ToolDefinition as PAToolDefinition

from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
from sevn.agent.adapters.tier_b_tools import (
    build_pydantic_tools_for_registry,
    prepare_lazy_tool_definitions,
)
from sevn.agent.adapters.tool_part_filter import MutableToolAllowlist
from sevn.agent.executors.b_types import BTierDeps
from sevn.tools.base import FunctionTool, ToolDefinition, ToolExecutor
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy

_GLOB_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "Glob pattern."},
        "path": {"type": "string", "description": "Base directory."},
    },
    "required": ["pattern"],
}

_LIST_DIR_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Directory path."},
    },
    "required": [],
}


def _ctx_template() -> ToolContext:
    return ToolContext(
        session_id="s",
        workspace_path=Path("/tmp"),
        workspace_id="w",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


def _deps(
    exe: ToolExecutor,
    *,
    loaded_tools: set[str] | None = None,
    registry_names: frozenset[str] | None = None,
) -> BTierDeps:
    allow = MutableToolAllowlist(
        base=frozenset({"load_tool"}),
        registry_names=registry_names or frozenset({"load_tool", "glob", "list_dir"}),
    )
    return BTierDeps(
        tool_executor=exe,
        tool_context_template=_ctx_template(),
        workspace_path=Path("/tmp"),
        registry_version=1,
        loaded_tools=loaded_tools if loaded_tools is not None else set(),
        tool_allowlist=allow,
    )


def _run_ctx(deps: BTierDeps) -> MagicMock:
    ctx = MagicMock()
    ctx.deps = deps
    return ctx


def _register_glob(exe: ToolExecutor) -> None:
    exe.register(
        FunctionTool(
            ToolDefinition(
                name="glob",
                category="file_ops",
                description="Glob files",
                parameters=_GLOB_SCHEMA,  # type: ignore[arg-type]
            ),
            lambda _ctx: json.dumps({"ok": True, "data": {"paths": []}}),
        ),
    )


def _register_list_dir(exe: ToolExecutor) -> None:
    exe.register(
        FunctionTool(
            ToolDefinition(
                name="list_dir",
                category="file_ops",
                description="List directory",
                parameters=_LIST_DIR_SCHEMA,  # type: ignore[arg-type]
            ),
            lambda _ctx: json.dumps({"ok": True, "data": {"entries": []}}),
        ),
    )


# ---------------------------------------------------------------------------
# W5.5 — minimal stub schema exposes path for list_dir
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_lazy_list_dir_stub_includes_path_property() -> None:
    """W5.5 / 1c: unseeded ``list_dir`` stub schema includes ``path`` (not empty ``{}``)."""
    exe = ToolExecutor()
    _register_list_dir(exe)
    deps = _deps(exe, loaded_tools=set())
    ctx = _run_ctx(deps)
    defs = [
        PAToolDefinition(
            name="list_dir",
            description="List directory",
            parameters_json_schema=_LIST_DIR_SCHEMA,  # type: ignore[arg-type]
        ),
    ]
    result = await prepare_lazy_tool_definitions(ctx, defs)
    assert result is not None
    props = result[0].parameters_json_schema.get("properties") or {}
    assert "path" in props
    assert "[SCHEMA NOT YET LOADED]" in (result[0].description or "")


# ---------------------------------------------------------------------------
# W5.4 — auto-grant on bad args, second call succeeds (unbound full-index tool)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stub_validation_auto_grant_then_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5.4 / 1b: unbound ``glob`` — bad args auto-grant; correct retry dispatches."""
    exe = ToolExecutor()
    _register_glob(exe)
    deps = _deps(exe, loaded_tools=set())
    ctx = _run_ctx(deps)

    captured: list[dict[str, object]] = []

    def _capture(event: str, **fields: object) -> None:
        if event == "tier_b.stub_validation_auto_grant":
            captured.append(dict(fields))

    monkeypatch.setattr(
        "sevn.agent.adapters.tier_b_tools.debug_event",
        _capture,
    )

    reg = PydanticToolRegistration(
        tool_names=("load_tool", "read"),
        tool_descriptions={},
        skill_names=(),
        skill_descriptions={},
    )
    glob_tool = next(t for t in build_pydantic_tools_for_registry(exe, reg) if t.name == "glob")

    dispatch = AsyncMock(return_value=json.dumps({"ok": True, "data": {"paths": ["a.py"]}}))
    deps.tool_executor.dispatch = dispatch  # type: ignore[method-assign]

    # First call: missing required ``pattern`` on stub schema → auto-grant steer.
    first = await glob_tool.function(ctx, path=".")
    assert ToolResultCode.VALIDATION_ERROR in first
    assert "Schema loaded" in first
    assert "glob" in deps.loaded_tools
    assert captured == [{"name": "glob"}]
    dispatch.assert_not_called()

    second = await glob_tool.function(ctx, pattern="**/*.py", path=".")
    assert ToolResultCode.VALIDATION_ERROR not in second
    assert "not provisioned" not in second
    dispatch.assert_called_once()
