"""W1 — eager tool hydration for small Triager sets (N=7).

Tests:
- ``eager_hydrate_tool_names`` returns correct names for small/large/core-only sets.
- ``prepare_lazy_tool_definitions`` returns full ``parameters_json_schema`` (no stub
  banner) when a tool is pre-seeded in ``BTierDeps.loaded_tools``.
- ``_dispatch_tool`` does NOT return the "not loaded" ``VALIDATION_ERROR`` when the
  tool is in ``BTierDeps.loaded_tools`` at construction time.
- ``full_index=True`` (~40 tools) still stubs unloaded tools.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.tools import ToolDefinition as PAToolDefinition

from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
from sevn.agent.adapters.tier_b_tools import (
    _NEVER_LAZY_NAMES,
    EAGER_HYDRATE_MAX_TOOLS,
    _dispatch_tool,
    eager_hydrate_tool_names,
    prepare_lazy_tool_definitions,
)
from sevn.agent.executors.b_types import BTierDeps
from sevn.tools.base import ToolDefinition, ToolExecutor
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SERP_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}


def _reg(*tool_names: str, descriptions: dict[str, str] | None = None) -> PydanticToolRegistration:
    return PydanticToolRegistration(
        tool_names=tool_names,
        tool_descriptions=descriptions or {},
        skill_names=(),
        skill_descriptions={},
    )


def _deps(loaded_tools: set[str] | None = None) -> BTierDeps:
    ctx = ToolContext(
        session_id="s",
        workspace_path=Path("/tmp"),
        workspace_id="w",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )
    return BTierDeps(
        tool_executor=ToolExecutor(),
        tool_context_template=ctx,
        workspace_path=Path("/tmp"),
        registry_version=1,
        loaded_tools=loaded_tools if loaded_tools is not None else set(),
    )


def _run_ctx(deps: BTierDeps) -> MagicMock:
    ctx = MagicMock()
    ctx.deps = deps
    return ctx


def _pa_tool(name: str, schema: dict[str, object] | None = None) -> PAToolDefinition:
    return PAToolDefinition(
        name=name,
        description=f"{name} description",
        parameters_json_schema=schema or _SERP_SCHEMA,
    )


# ---------------------------------------------------------------------------
# eager_hydrate_tool_names — unit tests
# ---------------------------------------------------------------------------


def test_eager_hydrate_constant_is_seven() -> None:
    assert EAGER_HYDRATE_MAX_TOOLS == 7


def test_eager_hydrate_single_serp_tool() -> None:
    reg = _reg("load_tool", "serp")
    result = eager_hydrate_tool_names(reg)
    assert result == frozenset({"serp"})


def test_eager_hydrate_core_only_is_empty() -> None:
    """All registered names are in _NEVER_LAZY_NAMES → nothing to eagerly seed."""
    core = tuple(_NEVER_LAZY_NAMES)
    reg = _reg(*core)
    assert eager_hydrate_tool_names(reg) == frozenset()


def test_eager_hydrate_exactly_seven_tools() -> None:
    tool_names = tuple(f"tool_{i}" for i in range(7))
    reg = _reg(*tool_names)
    result = eager_hydrate_tool_names(reg)
    assert result == frozenset(tool_names)


def test_eager_hydrate_eight_tools_returns_empty() -> None:
    """8 non-always-on tools exceeds the threshold → empty set (lazy stays)."""
    tool_names = tuple(f"tool_{i}" for i in range(8))
    reg = _reg(*tool_names)
    assert eager_hydrate_tool_names(reg) == frozenset()


def test_eager_hydrate_custom_threshold() -> None:
    tool_names = tuple(f"tool_{i}" for i in range(3))
    reg = _reg(*tool_names)
    assert eager_hydrate_tool_names(reg, threshold=2) == frozenset()
    assert eager_hydrate_tool_names(reg, threshold=3) == frozenset(tool_names)


# ---------------------------------------------------------------------------
# prepare_lazy_tool_definitions — eager path returns full schema (no stub)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_lazy_pre_seeded_serp_returns_full_schema() -> None:
    """A pre-seeded ``serp`` name must NOT be stubbed by prepare_lazy_tool_definitions."""
    deps = _deps(loaded_tools={"serp"})
    ctx = _run_ctx(deps)
    defs = [_pa_tool("serp", _SERP_SCHEMA)]
    result = await prepare_lazy_tool_definitions(ctx, defs)
    assert result is not None
    assert len(result) == 1
    td = result[0]
    # Full schema must be preserved (non-empty properties dict).
    assert td.parameters_json_schema.get("properties")
    # No stub banner in description.
    assert "[SCHEMA NOT YET LOADED]" not in (td.description or "")


@pytest.mark.asyncio
async def test_prepare_lazy_not_seeded_serp_returns_stub() -> None:
    """An unseeded ``serp`` name (empty loaded_tools) must still produce the stub banner."""
    deps = _deps(loaded_tools=set())
    ctx = _run_ctx(deps)
    defs = [_pa_tool("serp", _SERP_SCHEMA)]
    result = await prepare_lazy_tool_definitions(ctx, defs)
    assert result is not None
    td = result[0]
    # Stub schema has no properties.
    assert not td.parameters_json_schema.get("properties")
    assert "[SCHEMA NOT YET LOADED]" in (td.description or "")


@pytest.mark.asyncio
async def test_prepare_lazy_full_index_still_stubs() -> None:
    """~40 tools (full_index) are NOT pre-seeded → all remain stubbed."""
    many_names = [f"tool_{i}" for i in range(40)]
    # No seeding (empty loaded_tools simulates the threshold guard rejecting them).
    deps = _deps(loaded_tools=set())
    ctx = _run_ctx(deps)
    defs = [_pa_tool(n) for n in many_names]
    result = await prepare_lazy_tool_definitions(ctx, defs)
    assert result is not None
    for td in result:
        # All catalogue tools must be stubbed since nothing is in loaded_tools.
        assert "[SCHEMA NOT YET LOADED]" in (td.description or "")


# ---------------------------------------------------------------------------
# _dispatch_tool — no "not loaded" error when tool is pre-seeded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_tool_no_not_loaded_error_when_seeded() -> None:
    """Direct serp call with serp in loaded_tools must NOT return the VALIDATION_ERROR stub."""
    deps = _deps(loaded_tools={"serp"})
    ok_envelope = '{"ok": true, "result": "search results"}'
    deps.tool_executor.dispatch = AsyncMock(return_value=ok_envelope)  # type: ignore[method-assign]
    ctx = _run_ctx(deps)

    definition = ToolDefinition(
        name="serp",
        category="web",
        description="Web search",
        parameters=_SERP_SCHEMA,  # type: ignore[arg-type]
    )
    result = await _dispatch_tool(ctx, definition, {"query": "test"})
    # Must NOT contain the "not loaded" validation error.
    assert "not loaded" not in result
    assert ToolResultCode.VALIDATION_ERROR not in result
    # The executor should have been called.
    deps.tool_executor.dispatch.assert_called_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_dispatch_tool_not_loaded_error_when_not_seeded() -> None:
    """Direct serp call with empty loaded_tools must return the VALIDATION_ERROR envelope."""
    deps = _deps(loaded_tools=set())
    deps.tool_executor.dispatch = AsyncMock(return_value='{"ok": true}')  # type: ignore[method-assign]
    ctx = _run_ctx(deps)

    definition = ToolDefinition(
        name="serp",
        category="web",
        description="Web search",
        parameters=_SERP_SCHEMA,  # type: ignore[arg-type]
    )
    result = await _dispatch_tool(ctx, definition, {"query": "test"})
    assert "not provisioned" in result
    assert ToolResultCode.TOOL_NOT_PROVISIONED in result
    # Executor must NOT have been called.
    deps.tool_executor.dispatch.assert_not_called()  # type: ignore[attr-defined]
