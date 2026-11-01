"""PR #9 review: Ollama model ids, auto-approved shell, cancel locks, the bot cap,
and per-lane memory diffs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fakes.models import function_model
from support.botcore import arm_configured, upgrade_home
from support.canary import model_request_payloads, reset_model_requests
from support.chat import connected, fetch_all, load_modules, mint_id, ok, poll_rows, request


async def _create_bot(client: object, **extra: object) -> dict[str, object]:
    frame, _earlier = await request(
        client, "bots.create", {"name": "Nimbus", "op_id": mint_id("op_"), **extra}
    )
    return ok(frame)


def test_ollama_ids_are_selectable() -> None:
    from sevn.runtime.models import model_allowed

    assert model_allowed("ollama:llama3.2:3b")
    assert model_allowed("ollama:qwen3")
    assert not model_allowed("ollama:")
    assert not model_allowed("ollama: spaced")
    assert not model_allowed("made-up:model")


async def test_bots_update_keeps_an_ollama_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_modules("sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        bot = await _create_bot(client)
        frame, _earlier = await request(
            client,
            "bots.update",
            {"bot_id": bot["id"], "model": "ollama:llama3.2:3b", "op_id": mint_id("op_")},
        )
        assert ok(frame)["model"] == "ollama:llama3.2:3b"


async def test_auto_approved_low_risk_shell_finishes_the_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fakes.fake_jev import FakeJev
    from sevn.decisions.jev import use_client
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind

    reset_model_requests()
    load_modules("sevn.api.bots", "sevn.api.messages")
    use_client(FakeJev(answers={}))
    use_model(
        function_model(
            [
                [{"kind": "tool", "name": "shell", "args": {"command": "printf hi"}}],
                [{"kind": "text", "text": "all done"}],
            ]
        )
    )
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot = await _create_bot(client, access="full", approval_policy="auto")
            frame, _earlier = await request(
                client,
                "messages.send",
                {"bot_id": bot["id"], "text": "say hi", "op_id": mint_id("op_")},
            )
            sent = ok(frame)
            jobs = await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (sent["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] in {"done", "failed"},
            )
            assert jobs[0]["status"] == "done"
            assert fetch_all(tmp_path, "SELECT id FROM pending_requests") == []
            later = "\n".join(str(item) for item in model_request_payloads()[1:])
            assert "hi" in later
            replies = fetch_all(
                tmp_path,
                "SELECT parts FROM messages WHERE agent_id = ? AND role = 'assistant'",
                (sent["agent_id"],),
            )
            assert any("all done" in str(row["parts"]) for row in replies)
    finally:
        use_client(None)
        use_model(None)


async def _open_turn(agent_id: str, status: str) -> str:
    from sevn.domain.session import open_session
    from sevn.store.models import Agent, AgentLock, Job, Turn

    now = datetime.now(UTC)
    turn_id = mint_id("turn_")
    job_id = mint_id("job_")
    async with open_session() as session:
        agent = await session.get(Agent, agent_id)
        assert agent is not None
        agent.status = status
        session.add(
            Job(
                id=job_id,
                to_bot_id=agent.bot_id,
                agent_id=agent_id,
                route_decision_id=None,
                origin="user",
                text="edit the shared file",
                attachments=[],
                reply_to=None,
                expects_reply=True,
                hop=0,
                status="started",
                created_at=now,
                started_at=now,
                finished_at=None,
            )
        )
        session.add(
            Turn(
                id=turn_id,
                agent_id=agent_id,
                thread_id=agent.thread_id,
                job_ids=[job_id],
                status=status,
                model="test",
                usage={},
                model_messages=None,
                started_at=now,
                finished_at=None,
            )
        )
        session.add(
            AgentLock(
                path=f"shared/{turn_id}.txt",
                agent_id=agent_id,
                acquired_at=now,
                expires_at=now + timedelta(minutes=10),
            )
        )
        await session.commit()
    return turn_id


@pytest.mark.parametrize("status", ["running", "waiting"])
async def test_direct_cancel_drops_path_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.runtime.turn import cancel_persisted_waiting, persist_running_cancel

    load_modules("sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (host, client):
        bot = await _create_bot(client)
        agent = await AgentService().spawn(str(bot["id"]))
        turn_id = await _open_turn(agent.id, status)
        assert fetch_all(tmp_path, "SELECT path FROM agent_locks WHERE agent_id = ?", (agent.id,))
        cancel = persist_running_cancel if status == "running" else cancel_persisted_waiting
        assert await cancel(host.hub, turn_id) is True
        locks = fetch_all(tmp_path, "SELECT path FROM agent_locks WHERE agent_id = ?", (agent.id,))
        assert locks == []


async def _set_status(agent_id: str, status: str) -> None:
    from sevn.domain.session import open_session
    from sevn.store.models import Agent

    async with open_session() as session:
        row = await session.get(Agent, agent_id)
        assert row is not None
        row.status = status
        await session.commit()


async def test_follow_up_to_an_idle_agent_waits_for_a_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService

    load_modules("sevn.api.bots", "sevn.api.messages")
    async with connected(tmp_path, monkeypatch) as (host, client):
        bot = await _create_bot(client)
        for _ in range(3):
            busy = await AgentService().spawn(str(bot["id"]))
            await _set_status(busy.id, "running")
        idle = await AgentService().spawn(str(bot["id"]))
        frame, _earlier = await request(
            client,
            "messages.send",
            {
                "bot_id": bot["id"],
                "text": "and one more",
                "agent_id": idle.id,
                "op_id": mint_id("op_"),
            },
        )
        sent = ok(frame)
        assert sent["agent_id"] == idle.id
        stored = await host.outbox.since(0)
        queued = [row.payload for row in stored if row.type == "job.queued"]
        assert queued
        assert "ahead" in queued[-1], queued[-1]


async def test_follow_up_to_a_busy_agent_does_not_count_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService

    load_modules("sevn.api.bots", "sevn.api.messages")
    async with connected(tmp_path, monkeypatch) as (host, client):
        bot = await _create_bot(client)
        lanes = []
        for _ in range(3):
            busy = await AgentService().spawn(str(bot["id"]))
            await _set_status(busy.id, "running")
            lanes.append(busy)
        frame, _earlier = await request(
            client,
            "messages.send",
            {
                "bot_id": bot["id"],
                "text": "add this too",
                "agent_id": lanes[0].id,
                "op_id": mint_id("op_"),
            },
        )
        ok(frame)
        stored = await host.outbox.since(0)
        queued = [row.payload for row in stored if row.type == "job.queued"]
        assert queued
        assert "ahead" not in queued[-1], queued[-1]


async def test_each_lane_sees_a_memory_saved_by_a_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.bots import BotService
    from sevn.memory.context import render_user_block
    from sevn.memory.store import MemoryStore

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Nimbus")
    store = MemoryStore()
    first = mint_id("turn_")
    await store.save(bot.id, "the desk faces the window", turn_id=first)
    await store.commit(first)
    assert "the desk faces the window" in await render_user_block(
        bot.id, prior=False, agent_id="agent_a"
    )
    assert "the desk faces the window" in await render_user_block(
        bot.id, prior=False, agent_id="agent_b"
    )
    second = mint_id("turn_")
    await store.save(bot.id, "lunch is at noon", turn_id=second)
    await store.commit(second)
    seen_by_a = await render_user_block(bot.id, prior=True, agent_id="agent_a")
    seen_by_b = await render_user_block(bot.id, prior=True, agent_id="agent_b")
    assert "lunch is at noon" in seen_by_a
    assert "lunch is at noon" in seen_by_b
