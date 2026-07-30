"""W1.5 — harness Skills capability parity with tier_b_skill_capabilities (D7)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RunUsage
from pydantic_ai_harness.skills import Skills

from sevn.agent.adapters.tier_b_skills import (
    SkillCapabilitySource,
    build_harness_skills_capability,
    build_tier_b_skill_capabilities,
    sevn_run_skill_script,
    skill_capability,
)
from sevn.agent.executors.b_types import BTierDeps
from sevn.tools.base import ToolCall, ToolExecutor
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy


def _harness_skills_cls() -> type | None:
    try:
        from pydantic_ai_harness.skills import Skills
    except ImportError:
        return None
    return Skills


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


def test_build_tier_b_skill_capabilities_uses_harness_module() -> None:
    caps = build_tier_b_skill_capabilities(
        triage_skills=["pdf"],
        skill_descriptions={"pdf": "PDF helpers"},
        skills_manager=None,
        workspace_path=Path("/tmp"),
    )
    assert caps
    assert isinstance(caps[0], Skills)
    assert caps[0].__class__.__module__.startswith("pydantic_ai_harness")


@pytest.mark.asyncio
async def test_harness_skills_match_sevn_instructions_and_defer_load(
    tmp_path: Path,
) -> None:
    skills_cls = _harness_skills_cls()
    assert skills_cls is not None, "harness Skills not on installed wheel"

    skill_dir = tmp_path / "pdf"
    skill_dir.mkdir()
    body = "Runbook body for pdf skill."
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: pdf\ndescription: PDF helpers\n---\n\n{body}\n",
        encoding="utf-8",
    )

    sevn_cap = skill_capability(
        SkillCapabilitySource("pdf", "PDF helpers", body),
    )
    harness_caps = skills_cls(directories=[tmp_path])._deferred_capabilities
    harness_pdf = next(c for c in harness_caps if getattr(c, "id", "") == "pdf")

    assert sevn_cap.defer_loading is True
    assert harness_pdf.defer_loading is True
    assert body in "".join(harness_pdf.get_instructions())


@pytest.mark.asyncio
async def test_harness_skills_dispatch_sevn_run_skill_script() -> None:
    skills_cls = _harness_skills_cls()
    assert skills_cls is not None

    dispatched: list[str] = []

    async def fake_dispatch(ctx: ToolContext, call: ToolCall) -> object:
        dispatched.append(call.name)
        return {"ok": True}

    exe = ToolExecutor()
    exe.dispatch = AsyncMock(side_effect=fake_dispatch)  # type: ignore[method-assign]
    deps = _deps(executor=exe)
    ctx = _run_ctx(deps)

    await sevn_run_skill_script(
        ctx,
        skill="pdf",
        script="scripts/run.py",
        argv=[],
    )
    assert dispatched == ["run_skill_script"]

    async def model_fn(messages: list[object], info: MagicMock) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="ok")])

    skills_cap = build_harness_skills_capability(
        triage_skills=["pdf"],
        skill_descriptions={"pdf": "PDF"},
        skills_manager=None,
        workspace_path=Path("/tmp"),
    )
    assert skills_cap is not None

    agent = Agent(
        FunctionModel(model_fn),
        deps_type=BTierDeps,
        capabilities=[skills_cap],
    )
    await agent.run("skill dispatch", deps=deps)
    assert "run_skill_script" in dispatched
