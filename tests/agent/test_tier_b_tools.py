"""W1 — triager-bound direct tool enforcement tests (2026-06-04).

Tests:
- Narrowed turn seed: ``set(registration.tool_names) - _NEVER_LAZY_NAMES`` pre-seeds
  all triager-selected non-core tools, so ``serp`` is callable without ``load_tool``.
- Full-index seed: ``eager_hydrate_tool_names(registration)`` returns ∅ for >7 tools;
  the cap prevents schema bloat on the widened-retry pass.
- Direct ``serp`` dispatch succeeds when ``serp ∈ loaded_tools`` (no stub VALIDATION_ERROR).
- ``run_skill_runnable`` with ``runnable="serp"`` in ``known_tool_names`` triggers the
  ``SKILL_IS_ACTUALLY_TOOL`` steer naming ``serp``, not the ``skill`` payload key.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.tools import ToolDefinition as PAToolDefinition

from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
from sevn.agent.adapters.tier_b_tools import (
    _NEVER_LAZY_NAMES,
    _dispatch_tool,
    eager_hydrate_tool_names,
    prepare_lazy_tool_definitions,
)
from sevn.agent.executors.b_types import BTierDeps, SteerInject
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


def _reg(*tool_names: str) -> PydanticToolRegistration:
    return PydanticToolRegistration(
        tool_names=tool_names,
        tool_descriptions={},
        skill_names=(),
        skill_descriptions={},
    )


def _ctx_with_known(known: frozenset[str] | None = None) -> ToolContext:
    return ToolContext(
        session_id="s",
        workspace_path=Path("/tmp"),
        workspace_id="w",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        known_tool_names=known or frozenset(),
    )


def _deps(loaded_tools: set[str] | None = None, steer: SteerInject | None = None) -> BTierDeps:
    return BTierDeps(
        tool_executor=ToolExecutor(),
        tool_context_template=_ctx_with_known(),
        workspace_path=Path("/tmp"),
        registry_version=1,
        loaded_tools=loaded_tools if loaded_tools is not None else set(),
        steer_buffer=steer,
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
# W1.1 — seed logic: narrowed vs full_index paths
# ---------------------------------------------------------------------------


def test_narrowed_seed_includes_serp() -> None:
    """Narrowed turn: all non-core tools are seeded (``serp`` ∈ seeded set)."""
    reg = _reg("load_tool", "serp", "get_page_content")
    # Simulates the narrowed-turn seed formula from b_harness.py.
    seeded = set(reg.tool_names) - _NEVER_LAZY_NAMES
    assert "serp" in seeded
    assert "get_page_content" in seeded
    # Core tools are excluded.
    assert "load_tool" not in seeded


def test_narrowed_seed_excludes_never_lazy_names() -> None:
    """Narrowed turn: skill-runner, file-op, and meta names are never seeded."""
    core_names = tuple(_NEVER_LAZY_NAMES)
    reg = _reg(*core_names, "serp")
    seeded = set(reg.tool_names) - _NEVER_LAZY_NAMES
    for name in _NEVER_LAZY_NAMES:
        assert name not in seeded
    assert "serp" in seeded


def test_full_index_seed_empty_above_threshold() -> None:
    """Full-index retry with >7 tools: ``eager_hydrate_tool_names`` returns ∅."""
    many = tuple(f"tool_{i}" for i in range(40))
    reg = _reg(*many)
    seeded = set(eager_hydrate_tool_names(reg))
    assert seeded == set()


def test_full_index_seed_small_set_returns_names() -> None:
    """Full-index with ≤7 non-core tools: eager_hydrate_tool_names returns them."""
    reg = _reg("load_tool", "serp")
    seeded = set(eager_hydrate_tool_names(reg))
    assert "serp" in seeded
    assert "load_tool" not in seeded


# ---------------------------------------------------------------------------
# W1.1 — dispatch: serp in loaded_tools → no VALIDATION_ERROR stub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_serp_in_loaded_tools_succeeds() -> None:
    """Direct serp call with serp pre-seeded in loaded_tools must NOT return the not-loaded stub."""
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
    assert "not loaded" not in result
    assert ToolResultCode.VALIDATION_ERROR not in result
    deps.tool_executor.dispatch.assert_called_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_prepare_lazy_serp_seeded_returns_full_schema() -> None:
    """serp pre-seeded → prepare_lazy_tool_definitions exposes full JSON schema."""
    deps = _deps(loaded_tools={"serp"})
    ctx = _run_ctx(deps)
    defs = [_pa_tool("serp", _SERP_SCHEMA)]
    result = await prepare_lazy_tool_definitions(ctx, defs)
    assert result is not None
    assert len(result) == 1
    assert result[0].parameters_json_schema.get("properties")
    assert "[SCHEMA NOT YET LOADED]" not in (result[0].description or "")


@pytest.mark.asyncio
async def test_prepare_lazy_full_index_many_tools_all_stubbed() -> None:
    """full_index seed is ∅ for >7 tools → all catalogue tools remain stubbed."""
    many_names = [f"tool_{i}" for i in range(40)]
    deps = _deps(loaded_tools=set())  # no seeding — simulates full_index ∅ seed
    ctx = _run_ctx(deps)
    defs = [_pa_tool(n) for n in many_names]
    result = await prepare_lazy_tool_definitions(ctx, defs)
    assert result is not None
    for td in result:
        assert "[SCHEMA NOT YET LOADED]" in (td.description or "")


# ---------------------------------------------------------------------------
# W1.2 — steer precedence: run_skill_runnable SKILL_IS_ACTUALLY_TOOL names runnable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_is_actually_tool_steer_names_runnable_not_skill_key() -> None:
    """On first ``run_skill_runnable`` → ``SKILL_IS_ACTUALLY_TOOL``, steer receives
    ``steer_for_direct_tool_call("serp")`` (the runnable), NOT ``"browser-harness"``
    (the ``payload["skill"]`` fallback).

    This locks the ``did_you_mean_tool`` precedence over ``payload["skill"]`` in
    ``_dispatch_tool`` L316-318.
    """
    steer = SteerInject()
    deps = _deps(loaded_tools={"run_skill_runnable"}, steer=steer)
    deps.meta_tool_names = frozenset()

    # Envelope as returned by the new W1.2 guard:
    # ``_run_skill_runnable(skill="browser-harness", runnable="serp")`` →
    # ``_skill_is_actually_tool_envelope("serp")`` → ``did_you_mean_tool="serp"``.
    from sevn.tools.skills_register import _skill_is_actually_tool_envelope

    envelope_str = json.dumps(
        _skill_is_actually_tool_envelope("serp"),
        separators=(",", ":"),
        ensure_ascii=False,
    )
    deps.tool_executor.dispatch = AsyncMock(return_value=envelope_str)  # type: ignore[method-assign]

    definition = ToolDefinition(
        name="run_skill_runnable",
        category="skills",
        description="run skill runnable",
        parameters={
            "type": "object",
            "properties": {
                "skill": {"type": "string"},
                "runnable": {"type": "string"},
            },
        },
    )
    # payload["skill"] is "browser-harness" (a real skill, not the tool name).
    payload = {"skill": "browser-harness", "runnable": "serp"}

    await _dispatch_tool(_run_ctx(deps), definition, payload)

    # steer_buffer should have received the steer naming "serp" (the runnable hint).
    assert steer.pending_text is not None
    assert "serp" in steer.pending_text
    assert "browser-harness" not in steer.pending_text


# ---------------------------------------------------------------------------
# Fallback-tool routing: failure envelope with ``data.fallback_tool``
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_tool_envelope_grants_fallback_and_steers() -> None:
    """First failure naming ``data.fallback_tool`` grants the fallback for the
    turn and injects a steer telling the model to call it instead."""
    from sevn.tools.base import enveloped_failure
    from sevn.tools.registry import build_session_registry

    steer = SteerInject()
    exe, _tool_set = build_session_registry(registry_version=1)
    deps = BTierDeps(
        tool_executor=exe,
        tool_context_template=_ctx_with_known(),
        workspace_path=Path("/tmp"),
        registry_version=1,
        loaded_tools={"web_search"},
        steer_buffer=steer,
    )
    failure = enveloped_failure(
        "web_search requires a Brave Search API key in egress proxy secrets",
        code=ToolResultCode.PERMISSION_DENIED,
        data={"readiness": "needs_brave_key", "fallback_tool": "serp"},
    )
    deps.tool_executor.dispatch = AsyncMock(return_value=failure)  # type: ignore[method-assign]

    definition = ToolDefinition(
        name="web_search",
        category="web",
        description="Brave search",
        parameters=_SERP_SCHEMA,  # type: ignore[arg-type]
    )
    await _dispatch_tool(_run_ctx(deps), definition, {"query": "x"})

    assert "serp" in deps.loaded_tools
    assert steer.pending_text is not None
    assert "serp" in steer.pending_text
    assert "web_search" in steer.pending_text


@pytest.mark.asyncio
async def test_fallback_tool_not_in_catalog_is_not_granted() -> None:
    """A fallback name outside the enabled catalog must not be granted or steered."""
    from sevn.tools.base import enveloped_failure

    steer = SteerInject()
    deps = _deps(loaded_tools={"web_search"}, steer=steer)
    failure = enveloped_failure(
        "unavailable",
        code=ToolResultCode.PERMISSION_DENIED,
        data={"fallback_tool": "no_such_tool"},
    )
    deps.tool_executor.dispatch = AsyncMock(return_value=failure)  # type: ignore[method-assign]

    definition = ToolDefinition(
        name="web_search",
        category="web",
        description="Brave search",
        parameters=_SERP_SCHEMA,  # type: ignore[arg-type]
    )
    await _dispatch_tool(_run_ctx(deps), definition, {"query": "x"})

    assert "no_such_tool" not in deps.loaded_tools
    assert steer.pending_text is None
