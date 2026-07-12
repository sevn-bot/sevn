"""Tests for the ``spawn_subagent`` tool (W3.3/W3.4) — fake bodies, zero LLM calls."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sevn.agent.subagents.registry import SubAgentRegistry
from sevn.agent.subagents.supervisor import SubAgentSupervisor
from sevn.config.sections.subagents import SpecialistConfig, SubAgentsWorkspaceConfig
from sevn.tools.context import ToolContext
from sevn.tools.subagent_spawn import register_subagent_spawn_tools, spawn_subagent_tool


def _ctx(
    *,
    supervisor: SubAgentSupervisor | None,
    role: str | None = "tier_b",
    parent_id: str | None = "l1-parent",
    grants: frozenset[str] = frozenset(),
    remaining_budget_s: float | None = None,
) -> ToolContext:
    remaining_fn = (lambda: remaining_budget_s) if remaining_budget_s is not None else None
    return ToolContext(
        session_id="s1",
        workspace_path=Path("/tmp/w"),
        workspace_id="w1",
        registry_version=1,
        delivery_channel="telegram",
        subagent_supervisor=supervisor,
        subagent_role=role,
        subagent_parent_id=parent_id,
        subagent_specialist_grants=grants,
        subagent_remaining_budget_s=remaining_fn,
    )


async def _register_parent(registry: SubAgentRegistry) -> str:
    run = await registry.register(
        level=1,
        role="tier_b",
        session_id="s1",
        channel="telegram",
        task_summary="parent",
    )
    await registry.mark_running(run.id)
    return run.id


async def test_spawn_subagent_fire_and_forget_returns_run_id_immediately() -> None:
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry)
    parent_id = await _register_parent(registry)
    ctx = _ctx(supervisor=supervisor, parent_id=parent_id)

    out = json.loads(await spawn_subagent_tool(ctx, task="write a haiku about sevn"))

    assert out["ok"] is True
    assert out["data"]["mode"] == "fire_and_forget"
    run_id = out["data"]["run_id"]
    assert run_id

    # Give the spawned task a chance to run to completion (it's a fast placeholder body).
    for _ in range(20):
        run = await registry.get(run_id)
        assert run is not None
        if run.status.value == "done":
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("spawned run never reached 'done'")
    assert run.level == 2
    assert run.parent_id == parent_id


async def test_spawn_subagent_wait_true_blocks_and_returns_result() -> None:
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry)
    parent_id = await _register_parent(registry)
    ctx = _ctx(supervisor=supervisor, parent_id=parent_id, remaining_budget_s=30.0)

    out = json.loads(await spawn_subagent_tool(ctx, task="summarize the log", wait=True))

    assert out["ok"] is True
    assert out["data"]["status"] == "done"
    assert "summarize the log" in out["data"]["result"]


async def test_spawn_subagent_missing_task_is_validation_error() -> None:
    ctx = _ctx(supervisor=SubAgentSupervisor(SubAgentRegistry()))
    out = json.loads(await spawn_subagent_tool(ctx, task="   "))
    assert out["ok"] is False
    assert out["code"] == "VALIDATION_ERROR"


async def test_spawn_subagent_no_supervisor_returns_typed_failure() -> None:
    ctx = _ctx(supervisor=None)
    out = json.loads(await spawn_subagent_tool(ctx, task="do something"))
    assert out["ok"] is False
    assert out["code"] == "TOOL_NOT_PROVISIONED"


async def test_spawn_subagent_missing_l1_context_is_internal_error() -> None:
    ctx = _ctx(supervisor=SubAgentSupervisor(SubAgentRegistry()), role=None, parent_id=None)
    out = json.loads(await spawn_subagent_tool(ctx, task="do something"))
    assert out["ok"] is False
    assert out["code"] == "INTERNAL_ERROR"


async def test_spawn_subagent_level2_limit_exceeded_returns_tool_error_text() -> None:
    cfg = SubAgentsWorkspaceConfig(max_level2_default=0)
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry, config=cfg)
    parent_id = await _register_parent(registry)
    ctx = _ctx(supervisor=supervisor, parent_id=parent_id)

    out = json.loads(await spawn_subagent_tool(ctx, task="do something"))

    assert out["ok"] is False
    assert "limit" in out["error"].lower()


async def test_spawn_subagent_wait_true_timeout_kills_and_reports(
    monkeypatch,
) -> None:
    async def _slow_body(*, task: str, specialist: str | None) -> str:
        _ = task, specialist
        await asyncio.sleep(3600)
        return "unreachable"

    monkeypatch.setattr(
        "sevn.tools.subagent_spawn._placeholder_worker_body",
        _slow_body,
    )
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry)
    parent_id = await _register_parent(registry)
    ctx = _ctx(supervisor=supervisor, parent_id=parent_id, remaining_budget_s=0.05)

    out = json.loads(await spawn_subagent_tool(ctx, task="slow task", wait=True))

    assert out["ok"] is False
    assert out["code"] == "TOOL_TIMEOUT"


async def test_spawn_subagent_unknown_specialist_is_validation_error() -> None:
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry)
    parent_id = await _register_parent(registry)
    ctx = _ctx(supervisor=supervisor, parent_id=parent_id)

    out = json.loads(
        await spawn_subagent_tool(ctx, task="make an image", specialist="nonexistent"),
    )

    assert out["ok"] is False
    assert out["code"] == "VALIDATION_ERROR"


async def test_spawn_subagent_specialist_assigned_to_role_allowed() -> None:
    cfg = SubAgentsWorkspaceConfig(
        specialists={
            "media_generator": SpecialistConfig(
                model="minimax-3",
                provider="minimax",
                assigned_to=["tier_b"],
                requestable_by=["triager", "tier_b"],
            ),
        },
    )
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry, config=cfg)
    parent_id = await _register_parent(registry)
    ctx = _ctx(supervisor=supervisor, role="tier_b", parent_id=parent_id)

    out = json.loads(
        await spawn_subagent_tool(ctx, task="make an image", specialist="media_generator"),
    )

    assert out["ok"] is True
    assert out["data"]["run_id"]


async def test_spawn_subagent_specialist_denied_without_grant() -> None:
    cfg = SubAgentsWorkspaceConfig(
        specialists={
            "media_generator": SpecialistConfig(
                model="minimax-3",
                provider="minimax",
                assigned_to=["tier_b"],
                requestable_by=["triager", "tier_b"],
            ),
        },
    )
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry, config=cfg)
    parent_id = await registry.register(
        level=1,
        role="tier_c",
        session_id="s1",
        channel="telegram",
        task_summary="parent",
    )
    await registry.mark_running(parent_id.id)
    ctx = _ctx(supervisor=supervisor, role="tier_c", parent_id=parent_id.id)

    out = json.loads(
        await spawn_subagent_tool(ctx, task="make an image", specialist="media_generator"),
    )

    assert out["ok"] is False
    assert out["code"] == "PERMISSION_DENIED"


async def test_spawn_subagent_specialist_allowed_via_triager_grant() -> None:
    cfg = SubAgentsWorkspaceConfig(
        specialists={
            "media_generator": SpecialistConfig(
                model="minimax-3",
                provider="minimax",
                assigned_to=["tier_b"],
                requestable_by=["triager"],
            ),
        },
    )
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry, config=cfg)
    parent_id = await registry.register(
        level=1,
        role="tier_c",
        session_id="s1",
        channel="telegram",
        task_summary="parent",
    )
    await registry.mark_running(parent_id.id)

    ungranted_ctx = _ctx(supervisor=supervisor, role="tier_c", parent_id=parent_id.id)
    denied = json.loads(
        await spawn_subagent_tool(
            ungranted_ctx, task="make an image", specialist="media_generator"
        ),
    )
    assert denied["ok"] is False

    granted_ctx = _ctx(
        supervisor=supervisor,
        role="tier_c",
        parent_id=parent_id.id,
        grants=frozenset({"media_generator"}),
    )
    granted = json.loads(
        await spawn_subagent_tool(granted_ctx, task="make an image", specialist="media_generator"),
    )
    assert granted["ok"] is True


def test_register_subagent_spawn_tools_disabled_by_config() -> None:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.tools.base import ToolExecutor

    ws = WorkspaceConfig.minimal(subagents=SubAgentsWorkspaceConfig(enabled=False))
    exe = ToolExecutor()
    register_subagent_spawn_tools(exe, ws)
    assert "spawn_subagent" not in {d.name for d in exe.definitions()}
