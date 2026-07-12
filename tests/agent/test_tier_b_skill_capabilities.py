"""W6 / W15 — defer_loading skill capabilities scoped to ``triage.skills[]``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import Capability
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RunUsage

from sevn.agent.adapters.tier_b_skill_capabilities import (
    SkillCapabilitySource,
    build_tier_b_skill_capabilities,
    resolve_skill_capability_sources,
    sevn_run_skill_script,
    skill_capability,
)
from sevn.agent.executors.b_harness import build_tier_b_capabilities
from sevn.agent.executors.b_types import BTierDeps
from sevn.tools.base import ToolCall, ToolExecutor
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy


def _ctx() -> ToolContext:
    return ToolContext(
        session_id="s",
        workspace_path=Path("/tmp"),
        workspace_id="w",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


def _deps(*, executor: ToolExecutor | None = None) -> BTierDeps:
    return BTierDeps(
        tool_executor=executor or ToolExecutor(),
        tool_context_template=_ctx(),
        workspace_path=Path("/tmp"),
        registry_version=1,
    )


def _run_ctx(deps: BTierDeps) -> RunContext[BTierDeps]:
    return RunContext(deps=deps, model=MagicMock(), usage=RunUsage())


def test_skill_capability_sets_defer_loading_and_stable_id() -> None:
    cap = skill_capability(
        SkillCapabilitySource("pdf", "PDF helpers", "Runbook body for pdf."),
    )
    assert isinstance(cap, Capability)
    assert cap.id == "pdf"
    assert cap.defer_loading is True


def test_build_tier_b_skill_capabilities_scoped_to_triage_skills() -> None:
    caps = build_tier_b_skill_capabilities(
        triage_skills=["pdf"],
        skill_descriptions={
            "pdf": "PDF helpers",
            "graphify": "Code graph",
        },
        skills_manager=None,
    )
    assert len(caps) == 1
    assert caps[0].id == "pdf"
    assert caps[0].defer_loading is True


def test_build_tier_b_skill_capabilities_empty_when_no_skills() -> None:
    assert (
        build_tier_b_skill_capabilities(
            triage_skills=[],
            skill_descriptions={"pdf": "PDF helpers"},
            skills_manager=None,
        )
        == []
    )


@pytest.mark.asyncio
async def test_load_capability_round_trip_activates_instructions() -> None:
    source = SkillCapabilitySource("pdf", "PDF helpers", "Full pdf runbook.")
    cap = skill_capability(source)
    deps = _deps()

    async def model_fn(messages: list[object], info: MagicMock) -> ModelResponse:
        for msg in messages:
            for part in getattr(msg, "parts", ()):
                if (
                    getattr(part, "part_kind", "") == "tool-return"
                    and getattr(part, "tool_name", "") == "load_capability"
                ):
                    return ModelResponse(parts=[TextPart(content="done")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="load_capability",
                    args={"id": "pdf"},
                    tool_call_id="lc1",
                ),
            ],
        )

    agent = Agent(
        FunctionModel(model_fn),
        deps_type=BTierDeps,
        capabilities=[cap],
    )
    result = await agent.run("load pdf", deps=deps)

    load_returns = [
        part
        for msg in result.all_messages()
        for part in msg.parts
        if getattr(part, "part_kind", "") == "tool-return"
        and getattr(part, "tool_name", "") == "load_capability"
    ]
    assert len(load_returns) == 1
    content = load_returns[0].content
    assert isinstance(content, dict)
    assert "Full pdf runbook." in str(content.get("instructions", ""))


@pytest.mark.asyncio
async def test_loaded_skill_exposes_scoped_run_skill_script_tool() -> None:
    source = SkillCapabilitySource("pdf", "PDF helpers", "Runbook.")
    cap = skill_capability(source)
    ctx = _run_ctx(_deps())
    toolset = cap.get_toolset()
    assert toolset is not None
    tools = await toolset.get_tools(ctx)
    assert "pdf__run_skill_script" in tools


@pytest.mark.asyncio
async def test_sevn_run_skill_script_preserves_readiness_envelope() -> None:
    executor = ToolExecutor()
    readiness = {
        "ok": False,
        "code": "SKILL_NEEDS_ENV",
        "error": "Missing SECRET_API_KEY",
    }

    async def _dispatch(_ctx: ToolContext, call: ToolCall) -> str:
        assert call.name == "run_skill_script"
        assert call.arguments["skill"] == "needs_env"
        return json.dumps(readiness)

    executor.dispatch = AsyncMock(side_effect=_dispatch)  # type: ignore[method-assign]
    deps = _deps(executor=executor)
    ctx = _run_ctx(deps)
    raw = await sevn_run_skill_script(
        ctx,
        skill="needs_env",
        script="scripts/run.py",
        argv=["x"],
    )
    assert json.loads(raw) == readiness


def test_build_tier_b_capabilities_accepts_skill_extra() -> None:
    from pydantic_ai.capabilities.hooks import Hooks

    skill_caps = build_tier_b_skill_capabilities(
        triage_skills=["pdf"],
        skill_descriptions={"pdf": "PDF helpers"},
        skills_manager=None,
    )
    caps = build_tier_b_capabilities(hooks=Hooks(), extra=skill_caps)
    assert any(isinstance(c, Capability) and c.id == "pdf" for c in caps)


def test_resolve_skill_capability_sources_uses_manager_markdown(tmp_path: Path) -> None:
    import shutil

    from sevn.skills.manager import SkillsManager

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "skills" / "min_echo"
    dest = tmp_path / "skills" / "user" / "min_echo"
    dest.parent.mkdir(parents=True)
    shutil.copytree(fixture, dest)
    SkillsManager.reset_singletons_for_tests()
    mgr = SkillsManager.shared(tmp_path)
    sources = resolve_skill_capability_sources(
        skill_ids=["min_echo"],
        skill_descriptions={"min_echo": "Echo skill"},
        skills_manager=mgr,
    )
    SkillsManager.reset_singletons_for_tests()
    assert "Echoes positional arguments" in sources[0].instructions
