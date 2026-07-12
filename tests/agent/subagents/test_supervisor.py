"""Tests for ``sevn.agent.subagents.supervisor`` (D4/D5/D8/D9/D11) — fake bodies, zero LLM calls."""

from __future__ import annotations

import asyncio

import pytest

from sevn.agent.subagents.models import SubAgentLimitExceeded, SubAgentRun, SubAgentStatus
from sevn.agent.subagents.registry import SubAgentRegistry
from sevn.agent.subagents.supervisor import SubAgentHandle, SubAgentSpec, SubAgentSupervisor
from sevn.config.sections.subagents import SpecialistConfig, SubAgentsWorkspaceConfig


async def _noop() -> str:
    return "ok"


async def _sleep_forever() -> None:
    await asyncio.sleep(3600)


async def test_spawn_runs_body_and_marks_done() -> None:
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry)
    handle = await supervisor.spawn(
        SubAgentSpec(
            level=1, role="tier_b", body=_noop, session_id="s", channel="c", task_summary="t"
        ),
    )
    assert isinstance(handle, SubAgentHandle)
    result = await handle.task
    assert result is None  # _run's wrapper returns None; result lives in the announce-back call
    run = (await registry.snapshot())[0]
    assert run.status == SubAgentStatus.DONE
    assert run.finished_at is not None


async def test_spawn_level1_limit_returns_typed_result_not_exception() -> None:
    cfg = SubAgentsWorkspaceConfig(max_level1_default=1)
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry, config=cfg)
    spec = SubAgentSpec(
        level=1,
        role="tier_b",
        body=_sleep_forever,
        session_id="s",
        channel="c",
        task_summary="t",
    )
    first = await supervisor.spawn(spec)
    second = await supervisor.spawn(spec)
    assert isinstance(first, SubAgentHandle)
    assert isinstance(second, SubAgentLimitExceeded)
    assert second.reason == "level1_limit"
    assert second.limit == 1
    assert second.current == 1
    await supervisor.kill(first.id)


async def test_max_override_ceiling_wins_over_per_role_limit() -> None:
    cfg = SubAgentsWorkspaceConfig(max_override=1, max_level1_default=5)
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry, config=cfg)
    spec = SubAgentSpec(
        level=1,
        role="tier_b",
        body=_sleep_forever,
        session_id="s",
        channel="c",
        task_summary="t",
    )
    first = await supervisor.spawn(spec)
    second = await supervisor.spawn(spec)
    assert isinstance(first, SubAgentHandle)
    assert isinstance(second, SubAgentLimitExceeded)
    assert second.limit == 1
    await supervisor.kill(first.id)


async def test_level2_spawn_without_parent_id_raises_value_error() -> None:
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry)
    spec = SubAgentSpec(
        level=2,
        role="tier_b",
        body=_noop,
        session_id="s",
        channel="c",
        task_summary="t",
    )
    with pytest.raises(ValueError, match="parent_id"):
        await supervisor.spawn(spec)


async def test_level2_spawn_respects_max_level2_per_parent() -> None:
    cfg = SubAgentsWorkspaceConfig(max_level2_default=1)
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry, config=cfg)
    parent_handle = await supervisor.spawn(
        SubAgentSpec(
            level=1,
            role="tier_b",
            body=_sleep_forever,
            session_id="s",
            channel="c",
            task_summary="t",
        ),
    )
    child_spec = SubAgentSpec(
        level=2,
        role="tier_b",
        body=_sleep_forever,
        parent_id=parent_handle.id,
        session_id="s",
        channel="c",
        task_summary="t",
    )
    first_child = await supervisor.spawn(child_spec)
    second_child = await supervisor.spawn(child_spec)
    assert isinstance(first_child, SubAgentHandle)
    assert isinstance(second_child, SubAgentLimitExceeded)
    assert second_child.reason == "level2_limit"
    await supervisor.kill(parent_handle.id)  # cascades to first_child


async def test_specialist_max_concurrent_enforced_across_parents() -> None:
    cfg = SubAgentsWorkspaceConfig(
        specialists={
            "media_generator": SpecialistConfig(
                model="minimax-3", provider="minimax", max_concurrent=1
            )
        },
    )
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry, config=cfg)
    parent1 = await supervisor.spawn(
        SubAgentSpec(
            level=1,
            role="tier_b",
            body=_sleep_forever,
            session_id="s",
            channel="c",
            task_summary="t",
        ),
    )
    parent2 = await supervisor.spawn(
        SubAgentSpec(
            level=1,
            role="tier_b",
            body=_sleep_forever,
            session_id="s",
            channel="c",
            task_summary="t",
        ),
    )
    spec1 = SubAgentSpec(
        level=2,
        role="tier_b",
        body=_sleep_forever,
        parent_id=parent1.id,
        specialist="media_generator",
        session_id="s",
        channel="c",
        task_summary="t",
    )
    spec2 = SubAgentSpec(
        level=2,
        role="tier_b",
        body=_sleep_forever,
        parent_id=parent2.id,
        specialist="media_generator",
        session_id="s",
        channel="c",
        task_summary="t",
    )
    first = await supervisor.spawn(spec1)
    second = await supervisor.spawn(spec2)
    assert isinstance(first, SubAgentHandle)
    assert isinstance(second, SubAgentLimitExceeded)
    assert second.reason == "specialist_limit"
    assert second.specialist == "media_generator"
    await supervisor.kill(parent1.id)
    await supervisor.kill(parent2.id)


async def test_concurrent_spawn_race_enforces_cap_exactly() -> None:
    """20 concurrent spawns racing against cap=3: exactly 3 succeed (D5 atomicity)."""
    cfg = SubAgentsWorkspaceConfig(max_level1_default=3)
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry, config=cfg)
    spec = SubAgentSpec(
        level=1,
        role="tier_b",
        body=_sleep_forever,
        session_id="s",
        channel="c",
        task_summary="t",
    )
    results = await asyncio.gather(*[supervisor.spawn(spec) for _ in range(20)])
    handles = [r for r in results if isinstance(r, SubAgentHandle)]
    exceeded = [r for r in results if isinstance(r, SubAgentLimitExceeded)]
    assert len(handles) == 3
    assert len(exceeded) == 17
    await supervisor.kill_all()


async def test_kill_cascades_to_active_children() -> None:
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry)
    parent = await supervisor.spawn(
        SubAgentSpec(
            level=1,
            role="tier_b",
            body=_sleep_forever,
            session_id="s",
            channel="c",
            task_summary="t",
        ),
    )
    child = await supervisor.spawn(
        SubAgentSpec(
            level=2,
            role="tier_b",
            body=_sleep_forever,
            parent_id=parent.id,
            session_id="s",
            channel="c",
            task_summary="t",
        ),
    )
    killed = await supervisor.kill(parent.id, cascade=True)
    assert killed is True

    parent_run = next(r for r in await registry.snapshot() if r.id == parent.id)
    child_run = next(r for r in await registry.snapshot() if r.id == child.id)
    assert parent_run.status == SubAgentStatus.KILLED
    assert child_run.status == SubAgentStatus.KILLED


async def test_kill_unknown_id_returns_false() -> None:
    supervisor = SubAgentSupervisor(SubAgentRegistry())
    assert await supervisor.kill("nope") is False


async def test_kill_all_scoped_by_role() -> None:
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry)
    await supervisor.spawn(
        SubAgentSpec(
            level=1,
            role="tier_b",
            body=_sleep_forever,
            session_id="s",
            channel="c",
            task_summary="t",
        ),
    )
    await supervisor.spawn(
        SubAgentSpec(
            level=1,
            role="tier_c",
            body=_sleep_forever,
            session_id="s",
            channel="c",
            task_summary="t",
        ),
    )
    killed_count = await supervisor.kill_all(role="tier_b")
    assert killed_count == 1
    remaining = await registry.running(level=1)
    assert len(remaining) == 1
    assert remaining[0].role == "tier_c"
    await supervisor.kill_all()


async def test_timeout_marks_run_failed_not_killed() -> None:
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry)
    handle = await supervisor.spawn(
        SubAgentSpec(
            level=1,
            role="tier_b",
            body=_sleep_forever,
            session_id="s",
            channel="c",
            task_summary="t",
            timeout_s=0.01,
        ),
    )
    await handle.task
    run = (await registry.snapshot())[0]
    assert run.status == SubAgentStatus.FAILED


async def test_exception_in_body_marks_failed_and_announces_error() -> None:
    async def _boom() -> None:
        raise RuntimeError("body blew up")

    announced: list[tuple[SubAgentRun, object | None, BaseException | None]] = []

    async def _announce(
        run: SubAgentRun, result: object | None, error: BaseException | None
    ) -> None:
        announced.append((run, result, error))

    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry, announce_back=_announce)
    handle = await supervisor.spawn(
        SubAgentSpec(
            level=1, role="tier_b", body=_boom, session_id="s", channel="c", task_summary="t"
        ),
    )
    await handle.task
    run = (await registry.snapshot())[0]
    assert run.status == SubAgentStatus.FAILED
    assert len(announced) == 1
    announced_run, result, error = announced[0]
    assert announced_run.status == SubAgentStatus.FAILED
    assert result is None
    assert isinstance(error, RuntimeError)


async def test_announce_back_invoked_on_success_with_result() -> None:
    announced: list[tuple[SubAgentRun, object | None, BaseException | None]] = []

    async def _announce(
        run: SubAgentRun, result: object | None, error: BaseException | None
    ) -> None:
        announced.append((run, result, error))

    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry, announce_back=_announce)
    handle = await supervisor.spawn(
        SubAgentSpec(
            level=1, role="tier_b", body=_noop, session_id="s", channel="c", task_summary="t"
        ),
    )
    await handle.task
    assert len(announced) == 1
    run, result, error = announced[0]
    assert run.status == SubAgentStatus.DONE
    assert result == "ok"
    assert error is None


async def test_announce_back_hook_failure_is_swallowed() -> None:
    async def _boom_announce(
        _run: SubAgentRun, _result: object | None, _error: BaseException | None
    ) -> None:
        raise RuntimeError("announce transport unavailable")

    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry, announce_back=_boom_announce)
    handle = await supervisor.spawn(
        SubAgentSpec(
            level=1, role="tier_b", body=_noop, session_id="s", channel="c", task_summary="t"
        ),
    )
    # Must not raise despite the announce-back hook always failing.
    await handle.task
    run = (await registry.snapshot())[0]
    assert run.status == SubAgentStatus.DONE
