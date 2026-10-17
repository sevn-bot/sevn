"""messages.send routing and cursor paging (green after W4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fakes.models import function_model
from support.chat import (
    assert_prefixed_id,
    connected,
    fetch_all,
    load_modules,
    mint_id,
    ok,
    poll_rows,
    request,
)

pytestmark = pytest.mark.xfail(reason="green after W4", strict=False)


async def _create_bot(client: object, name: str = "Nimbus") -> dict[str, object]:
    frame, _earlier = await request(
        client,
        "bots.create",
        {"name": name, "op_id": mint_id("op_")},
    )
    return ok(frame)


async def _send(client: object, bot_id: object, text: str, **extra: object) -> dict[str, object]:
    frame, _earlier = await request(
        client,
        "messages.send",
        {"bot_id": bot_id, "text": text, "op_id": mint_id("op_"), **extra},
    )
    return ok(frame)


def _install_fast_model() -> None:
    from sevn.runtime.models import use_model

    use_model(function_model([{"kind": "text", "text": "ok"}]))


async def _wait_done(home: Path, job_id: str) -> None:
    await poll_rows(
        home,
        "SELECT status FROM jobs WHERE id = ?",
        (job_id,),
        lambda rows: bool(rows) and rows[0]["status"] == "done",
    )


async def test_send_creates_job_and_agent_when_none_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.worker import bind

    load_modules("sevn.api.bots", "sevn.api.messages")
    _install_fast_model()
    async with connected(tmp_path, monkeypatch) as (host, client):
        bind(host.hub)
        bot = await _create_bot(client)
        body = await _send(client, bot["id"], "hi")
        job_id = assert_prefixed_id(body["job_id"], "job_")
        agent_id = assert_prefixed_id(body["agent_id"], "agent_")
        await _wait_done(tmp_path, job_id)
        jobs = fetch_all(tmp_path, "SELECT to_bot_id, agent_id, text, status FROM jobs")
        assert len(jobs) == 1
        assert jobs[0]["to_bot_id"] == bot["id"]
        assert jobs[0]["agent_id"] == agent_id
        assert jobs[0]["text"] == "hi"
        assert jobs[0]["status"] == "done"
        agents = fetch_all(tmp_path, "SELECT id FROM agents")
        assert [row["id"] for row in agents] == [agent_id]
        stored = await host.outbox.since(0)
        assert any(row.type == "job.queued" for row in stored)


async def test_send_follow_up_goes_to_latest_open_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.worker import bind

    load_modules("sevn.api.bots", "sevn.api.messages")
    _install_fast_model()
    async with connected(tmp_path, monkeypatch) as (host, client):
        bind(host.hub)
        bot = await _create_bot(client)
        first = await _send(client, bot["id"], "one")
        await _wait_done(tmp_path, str(first["job_id"]))
        second = await _send(client, bot["id"], "two")
        assert second["agent_id"] == first["agent_id"]
        await _wait_done(tmp_path, str(second["job_id"]))
        agents = fetch_all(tmp_path, "SELECT id FROM agents")
        assert len(agents) == 1


async def test_send_with_new_agent_true_starts_second_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.worker import bind

    load_modules("sevn.api.bots", "sevn.api.messages")
    _install_fast_model()
    async with connected(tmp_path, monkeypatch) as (host, client):
        bind(host.hub)
        bot = await _create_bot(client)
        first = await _send(client, bot["id"], "one")
        await _wait_done(tmp_path, str(first["job_id"]))
        second = await _send(client, bot["id"], "two", new_agent=True)
        assert second["agent_id"] != first["agent_id"]
        assert_prefixed_id(second["agent_id"], "agent_")
        agents = fetch_all(tmp_path, "SELECT id FROM agents")
        assert {row["id"] for row in agents} == {first["agent_id"], second["agent_id"]}


async def test_send_with_agent_id_targets_that_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.worker import bind

    load_modules("sevn.api.bots", "sevn.api.messages")
    _install_fast_model()
    async with connected(tmp_path, monkeypatch) as (host, client):
        bind(host.hub)
        bot = await _create_bot(client)
        first = await _send(client, bot["id"], "one")
        await _wait_done(tmp_path, str(first["job_id"]))
        second = await _send(client, bot["id"], "two", new_agent=True)
        await _wait_done(tmp_path, str(second["job_id"]))
        targeted = await _send(client, bot["id"], "back", agent_id=first["agent_id"])
        assert targeted["agent_id"] == first["agent_id"]
        jobs = fetch_all(
            tmp_path,
            "SELECT agent_id FROM jobs WHERE id = ?",
            (targeted["job_id"],),
        )
        assert jobs[0]["agent_id"] == first["agent_id"]


async def test_messages_list_pages_by_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.store.db import async_engine
    from sevn.store.models import Message, Turn
    from sqlalchemy.ext.asyncio import async_sessionmaker

    load_modules("sevn.api.bots", "sevn.api.messages")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        bot = await _create_bot(client)
        agent = await AgentService().spawn(bot_id=str(bot["id"]))
        thread_id = agent.thread_id
        turn_id = mint_id("turn_")
        engine = async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sevn.db'}")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        start = datetime(2026, 1, 1, tzinfo=UTC)
        try:
            async with sessions() as session:
                session.add(
                    Turn(
                        id=turn_id,
                        agent_id=agent.id,
                        thread_id=thread_id,
                        job_ids=[],
                        status="done",
                        model="anthropic",
                        usage={},
                        model_messages=[],
                        started_at=start,
                        finished_at=start,
                    )
                )
                for index in range(120):
                    session.add(
                        Message(
                            id=f"msg_{index:026d}",
                            thread_id=thread_id,
                            turn_id=turn_id,
                            agent_id=agent.id,
                            role="user",
                            author="user",
                            parts=[{"type": "text", "text": f"m{index}"}],
                            created_at=start + timedelta(seconds=index),
                        )
                    )
                await session.commit()
        finally:
            await engine.dispose()

        first, _earlier = await request(client, "messages.list", {"bot_id": bot["id"]})
        page1 = ok(first)
        again, _earlier = await request(client, "messages.list", {"bot_id": bot["id"]})
        stable = ok(again)
        assert [item["id"] for item in page1["messages"]] == [
            item["id"] for item in stable["messages"]
        ]
        assert len(page1["messages"]) == 50
        assert page1["messages"][0]["id"] == f"msg_{119:026d}"
        assert page1["messages"][-1]["id"] == f"msg_{70:026d}"
        cursor = page1["next_cursor"]
        assert isinstance(cursor, str) and cursor

        second, _earlier = await request(
            client,
            "messages.list",
            {"bot_id": bot["id"], "cursor": cursor},
        )
        page2 = ok(second)
        assert len(page2["messages"]) == 50
        assert page2["messages"][0]["id"] == f"msg_{69:026d}"
        cursor2 = page2["next_cursor"]
        assert isinstance(cursor2, str) and cursor2 != cursor

        third, _earlier = await request(
            client,
            "messages.list",
            {"bot_id": bot["id"], "cursor": cursor2},
        )
        page3 = ok(third)
        assert len(page3["messages"]) == 20
        assert page3["messages"][-1]["id"] == f"msg_{0:026d}"
        assert page3["next_cursor"] is None
        seen = [item["id"] for item in [*page1["messages"], *page2["messages"], *page3["messages"]]]
        assert seen == [f"msg_{index:026d}" for index in range(119, -1, -1)]
