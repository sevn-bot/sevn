"""Controlled interleavings for PR9's job, cancellation, and memory review findings."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from sevn.domain.agents import AgentService
from sevn.domain.bots import BotService
from sevn.domain.errors import DomainError
from sevn.domain.session import open_session
from sevn.memory.store import MemoryStore
from sevn.runtime.models import use_model
from sevn.runtime.worker import bind
from support.botcore import arm_configured, upgrade_home
from support.chat import connected, fetch_all, load_modules, mint_id, ok, poll_rows, request


async def test_reroute_invalidates_a_job_selected_by_the_old_pump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof")
    selected, release_pump, model_started, release_model = (asyncio.Event() for _ in range(4))
    calls = 0

    async def respond(_messages, _info):
        nonlocal calls
        calls += 1
        model_started.set()
        await release_model.wait()
        return ModelResponse(parts=[TextPart("ok")])

    use_model(FunctionModel(respond))
    load_modules("sevn.api.bots", "sevn.api.messages")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            worker = bind(host.hub)
            reserve = worker._reserve
            first = True

            async def pause_reserve(agent_id):
                nonlocal first
                if first:
                    first = False
                    selected.set()
                    await release_pump.wait()
                return await reserve(agent_id)

            monkeypatch.setattr(worker, "_reserve", pause_reserve)
            sent = ok(
                (
                    await request(
                        client,
                        "messages.send",
                        {"bot_id": bot.id, "text": "move me", "op_id": mint_id("op_")},
                    )
                )[0]
            )
            await asyncio.wait_for(selected.wait(), 5)
            target = await AgentService().spawn(bot.id)
            message_id = fetch_all(tmp_path, "SELECT id FROM messages WHERE role='user'")[0]["id"]
            ok(
                (
                    await request(
                        client,
                        "messages.reroute",
                        {"message_id": message_id, "agent_id": target.id, "op_id": mint_id("op_")},
                    )
                )[0]
            )
            await asyncio.wait_for(model_started.wait(), 5)
            release_pump.set()
            await asyncio.wait_for(worker._tasks[sent["agent_id"]], 5)
            assert calls == 1
            release_model.set()
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id=?",
                (sent["job_id"],),
                lambda rows: rows[0]["status"] == "done",
            )
            assert calls == 1
    finally:
        release_pump.set()
        release_model.set()
        use_model(None)


async def test_atomic_claim_only_starts_a_queued_job_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.jobs import JobService
    from sevn.runtime.turn import _mark_started

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof")
    agent = await AgentService().spawn(bot.id)
    job_id = mint_id("job_")
    await JobService().enqueue(job_id, bot.id, agent.id, "one operation")
    claims = await asyncio.gather(*(_mark_started(job_id, agent_id=agent.id) for _ in range(2)))
    assert sum(claim is not None for claim in claims) == 1
    assert await _mark_started(job_id, agent_id=agent.id) is None


@pytest.mark.parametrize("finish", ["commit", "rollback", "close"])
async def test_memory_reservation_survives_write_until_transaction_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, finish: str
) -> None:
    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof")
    store = MemoryStore()
    first, second = mint_id("turn_"), mint_id("turn_")
    await store.save(bot.id, "a" * 3000, tier="pinned", turn_id=first)
    async with open_session() as session:
        await store.write(session, first)
        await session.flush()  # Flush's nested transaction must not release the reservation.
        with pytest.raises(DomainError, match="pinned memory budget exceeded") as caught:
            await store.save(bot.id, "b" * 1500, tier="pinned", turn_id=second)
        assert caught.value.code == "pinned_budget"
        if finish == "commit":
            await session.commit()
        elif finish == "rollback":
            await session.rollback()
    size = 1000 if finish == "commit" else 3500
    await store.save(bot.id, "c" * size, tier="pinned", turn_id=second)
    await store.commit(second)
    assert sum(len(row.text) for row in await store.list_for(bot.id)) == (
        4000 if finish == "commit" else 3500
    )


async def test_cancel_transient_question_wait_stops_model_before_unlocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.workspace import acquire_write

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof")
    started, stopped, release = (asyncio.Event() for _ in range(3))
    calls = 0
    side_effects = []

    async def respond(_messages, _info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[ToolCallPart("user.ask", {"question": "When?"}, "question_1")]
            )
        started.set()
        try:
            await release.wait()
            side_effects.append("late write")
            return ModelResponse(parts=[TextPart("done")])
        finally:
            stopped.set()

    use_model(FunctionModel(respond))
    load_modules("sevn.api.bots", "sevn.api.messages")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            sent = ok(
                (
                    await request(
                        client,
                        "messages.send",
                        {"bot_id": bot.id, "text": "ask then wait", "op_id": mint_id("op_")},
                    )
                )[0]
            )
            await asyncio.wait_for(started.wait(), 5)
            turn = fetch_all(
                tmp_path, "SELECT id, status FROM turns WHERE agent_id=?", (sent["agent_id"],)
            )[0]
            assert turn["status"] == "waiting"
            path = str(Path(bot.workspace_path) / "shared" / "fixture.txt")
            await acquire_write(sent["agent_id"], path)
            result = ok(
                (
                    await request(
                        client, "turns.cancel", {"turn_id": turn["id"], "op_id": mint_id("op_")}
                    )
                )[0]
            )
            assert result["status"] == "cancelled"
            assert stopped.is_set()
            sibling = await AgentService().spawn(bot.id)
            await acquire_write(sibling.id, path)
            release.set()
            assert not side_effects
    finally:
        release.set()
        use_model(None)


@pytest.mark.parametrize("action", ["cancel", "reroute"])
async def test_claim_registration_is_serialized_with_lane_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from sevn.domain.jobs import job_lock
    from sevn.runtime import turn as turn_module

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof")
    claimed, release_claim, release_model = (asyncio.Event() for _ in range(3))
    original = turn_module._previous_messages
    first = True
    active = maximum = 0

    async def pause_history(agent_id):
        nonlocal first
        if first:
            first = False
            claimed.set()
            await release_claim.wait()
        return await original(agent_id)

    async def respond(_messages, _info):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        try:
            await release_model.wait()
            return ModelResponse(parts=[TextPart("ok")])
        finally:
            active -= 1

    monkeypatch.setattr(turn_module, "_previous_messages", pause_history)
    use_model(FunctionModel(respond))
    load_modules("sevn.api.bots", "sevn.api.messages")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            worker = bind(host.hub)
            sent = ok(
                (
                    await request(
                        client,
                        "messages.send",
                        {"bot_id": bot.id, "text": "claim then move", "op_id": mint_id("op_")},
                    )
                )[0]
            )
            await asyncio.wait_for(claimed.wait(), 5)
            assert job_lock(sent["job_id"]).locked()
            turn_id = fetch_all(
                tmp_path, "SELECT id FROM turns WHERE agent_id=?", (sent["agent_id"],)
            )[0]["id"]
            if action == "cancel":
                change = asyncio.create_task(worker.cancel(turn_id))
            else:
                target = await AgentService().spawn(bot.id)
                change = asyncio.create_task(
                    worker.interrupt_and_requeue(sent["job_id"], target.id)
                )
            await asyncio.sleep(0)
            assert not change.done()
            release_claim.set()
            await asyncio.wait_for(change, 5)
            assert (
                fetch_all(tmp_path, "SELECT status FROM turns WHERE id=?", (turn_id,))[0]["status"]
                == "cancelled"
            )
            assert active == 0
            if action == "reroute":
                worker.kick(target.id)
                release_model.set()
                await poll_rows(
                    tmp_path,
                    "SELECT status FROM jobs WHERE id=?",
                    (sent["job_id"],),
                    lambda rows: rows[0]["status"] == "done",
                )
            else:
                assert (
                    fetch_all(tmp_path, "SELECT status FROM jobs WHERE id=?", (sent["job_id"],))[0][
                        "status"
                    ]
                    == "cancelled"
                )
            assert maximum <= 1
    finally:
        release_claim.set()
        release_model.set()
        use_model(None)


async def test_reroute_rejects_completion_during_turn_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.jobs import JobService
    from sevn.runtime import worker as worker_module
    from sevn.store.models import Job

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof")
    source = await AgentService().spawn(bot.id)
    target = await AgentService().spawn(bot.id)
    job_id = mint_id("job_")
    await JobService().enqueue(job_id, bot.id, source.id, "already finished")

    async def finish_before_lookup(_job_id):
        async with open_session() as session:
            row = await session.get(Job, job_id)
            row.status = "done"
            await session.commit()
        return None

    monkeypatch.setattr(worker_module, "_open_turn_for_job", finish_before_lookup)
    async with connected(tmp_path, monkeypatch) as (host, _client):
        worker = bind(host.hub)
        with pytest.raises(DomainError, match="message already finished") as caught:
            await worker.interrupt_and_requeue(job_id, target.id)
        assert caught.value.code == "invalid_params"
        job = fetch_all(tmp_path, "SELECT status, agent_id FROM jobs WHERE id=?", (job_id,))[0]
        assert job["status"] == "done"
        assert job["agent_id"] == source.id


async def test_memory_reservation_snapshot_precedes_database_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import asynccontextmanager

    from sevn.memory import store as memory_module

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof")
    store = MemoryStore()
    first, second = mint_id("turn_"), mint_id("turn_")
    await store.save(bot.id, "a" * 3000, tier="pinned", turn_id=first)
    async with open_session() as writer:
        await store.write(writer, first)
        await writer.flush()
        original = memory_module.open_session

        @asynccontextmanager
        async def commit_after_read():
            async with original() as reader:
                yield reader
            await writer.commit()

        monkeypatch.setattr(memory_module, "open_session", commit_after_read)
        with pytest.raises(DomainError, match="pinned memory budget exceeded") as caught:
            await store.save(bot.id, "b" * 1500, tier="pinned", turn_id=second)
        assert caught.value.code == "pinned_budget"
    monkeypatch.setattr(memory_module, "open_session", original)
    assert sum(len(row.text) for row in await store.list_for(bot.id)) == 3000
