"""Tests for ``sevn.agent.subagents.registry`` (D3/D10) — zero LLM calls, fake bodies only."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus, generate_short_id
from sevn.agent.subagents.registry import SubAgentRegistry

if TYPE_CHECKING:
    from sevn.agent.subagents.registry import RegistrySnapshot


async def test_register_creates_pending_run() -> None:
    registry = SubAgentRegistry()
    run = await registry.register(
        level=1,
        role="tier_b",
        session_id="s1",
        channel="telegram",
        task_summary="hi",
    )
    assert run.status == SubAgentStatus.PENDING
    assert run.level == 1
    assert run.role == "tier_b"
    assert run.parent_id is None
    assert len(run.id) >= 4


async def test_register_ids_are_unique() -> None:
    registry = SubAgentRegistry()
    ids = set()
    for _ in range(25):
        run = await registry.register(
            level=1,
            role="tier_b",
            session_id="s1",
            channel="c",
            task_summary="t",
        )
        ids.add(run.id)
    assert len(ids) == 25


async def test_mark_transitions_update_status_and_finished_at() -> None:
    registry = SubAgentRegistry()
    run = await registry.register(
        level=1,
        role="tier_b",
        session_id="s1",
        channel="c",
        task_summary="t",
    )
    running = await registry.mark_running(run.id)
    assert running.status == SubAgentStatus.RUNNING
    assert running.finished_at is None

    done = await registry.mark_done(run.id, now_ns=1234)
    assert done.status == SubAgentStatus.DONE
    assert done.finished_at == 1234


async def test_mark_failed_and_killed_and_orphaned() -> None:
    registry = SubAgentRegistry()
    run = await registry.register(
        level=1,
        role="tier_c",
        session_id="s1",
        channel="c",
        task_summary="t",
    )
    await registry.mark_running(run.id)
    failed = await registry.mark_failed(run.id, now_ns=2)
    assert failed.status == SubAgentStatus.FAILED
    assert failed.finished_at == 2

    run2 = await registry.register(
        level=2,
        role="tier_c",
        parent_id=run.id,
        session_id="s1",
        channel="c",
        task_summary="t",
    )
    killed = await registry.mark_killed(run2.id, now_ns=3)
    assert killed.status == SubAgentStatus.KILLED

    run3 = await registry.register(
        level=1,
        role="tier_d",
        session_id="s1",
        channel="c",
        task_summary="t",
    )
    orphaned = await registry.mark_orphaned(run3.id, now_ns=4)
    assert orphaned.status == SubAgentStatus.ORPHANED


async def test_mark_unknown_id_raises_key_error() -> None:
    registry = SubAgentRegistry()
    with pytest.raises(KeyError):
        await registry.mark_running("nope")


async def test_counts_only_reflects_active_statuses() -> None:
    registry = SubAgentRegistry()
    a = await registry.register(
        level=1, role="tier_b", session_id="s", channel="c", task_summary="t"
    )
    b = await registry.register(
        level=1, role="tier_b", session_id="s", channel="c", task_summary="t"
    )
    await registry.register(
        level=2, role="tier_c", parent_id=a.id, session_id="s", channel="c", task_summary="t"
    )
    await registry.mark_running(a.id)
    await registry.mark_done(b.id)

    counts = await registry.counts()
    assert counts[(1, "tier_b")] == 1  # only `a` (running); `b` is done, no longer active
    assert counts[(2, "tier_c")] == 1


async def test_running_filters_by_level_and_role() -> None:
    registry = SubAgentRegistry()
    b_run = await registry.register(
        level=1, role="tier_b", session_id="s", channel="c", task_summary="t"
    )
    await registry.register(level=1, role="tier_c", session_id="s", channel="c", task_summary="t")

    only_b = await registry.running(level=1, role="tier_b")
    assert [r.id for r in only_b] == [b_run.id]

    both = await registry.running(level=1)
    assert len(both) == 2


async def test_children_of_returns_full_history_any_status() -> None:
    registry = SubAgentRegistry()
    parent = await registry.register(
        level=1, role="tier_b", session_id="s", channel="c", task_summary="t"
    )
    child = await registry.register(
        level=2,
        role="tier_b",
        parent_id=parent.id,
        session_id="s",
        channel="c",
        task_summary="t",
    )
    await registry.mark_running(child.id)
    await registry.mark_done(child.id)

    children = await registry.children_of(parent.id)
    assert len(children) == 1
    assert children[0].id == child.id
    assert children[0].status == SubAgentStatus.DONE


async def test_snapshot_returns_all_runs() -> None:
    registry = SubAgentRegistry()
    await registry.register(level=1, role="tier_b", session_id="s", channel="c", task_summary="t")
    await registry.register(level=1, role="tier_c", session_id="s", channel="c", task_summary="t")
    snap = await registry.snapshot()
    assert len(snap) == 2


async def test_register_if_atomically_enforces_a_cap_under_concurrency() -> None:
    """Two concurrent register_if calls racing against cap=1: exactly one wins."""
    registry = SubAgentRegistry()

    def _predicate(snap: RegistrySnapshot) -> bool:
        return snap.counts().get((1, "tier_b"), 0) < 1

    results = await asyncio.gather(
        *[
            registry.register_if(
                _predicate,
                level=1,
                role="tier_b",
                session_id="s",
                channel="c",
                task_summary="t",
            )
            for _ in range(10)
        ],
    )
    succeeded = [r for r in results if r is not None]
    assert len(succeeded) == 1


async def test_register_if_rejects_when_predicate_false() -> None:
    registry = SubAgentRegistry()
    result = await registry.register_if(
        lambda _snap: False,
        level=1,
        role="tier_b",
        session_id="s",
        channel="c",
        task_summary="t",
    )
    assert result is None
    assert await registry.snapshot() == ()


async def test_persist_hook_invoked_on_every_transition() -> None:
    persisted: list[SubAgentRun] = []

    async def _fake_persist(run: SubAgentRun) -> None:
        persisted.append(run)

    registry = SubAgentRegistry(persist=_fake_persist)
    run = await registry.register(
        level=1, role="tier_b", session_id="s", channel="c", task_summary="t"
    )
    await registry.mark_running(run.id)
    await registry.mark_done(run.id)

    assert [p.status for p in persisted] == [
        SubAgentStatus.PENDING,
        SubAgentStatus.RUNNING,
        SubAgentStatus.DONE,
    ]


async def test_persist_hook_failure_is_swallowed_not_raised() -> None:
    async def _boom(_run: SubAgentRun) -> None:
        raise RuntimeError("persistence backend unavailable")

    registry = SubAgentRegistry(persist=_boom)
    # Must not raise despite the hook always failing.
    run = await registry.register(
        level=1, role="tier_b", session_id="s", channel="c", task_summary="t"
    )
    updated = await registry.mark_running(run.id)
    assert updated.status == SubAgentStatus.RUNNING


def test_generate_short_id_widens_on_exhaustion() -> None:
    existing = {"0"}
    new_id = generate_short_id(existing, length=1, max_attempts=1)
    assert new_id not in existing
    assert len(new_id) >= 1
