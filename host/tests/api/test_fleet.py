"""fleet.overview: the main dashboard read model (plan fleet-dashboards, phase 1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from support.chat import connected, load_modules, mint_id, ok, request


async def _bot(client: object, name: str) -> str:
    frame, _earlier = await request(client, "bots.create", {"name": name, "op_id": mint_id("op_")})
    bot_id = ok(frame)["id"]
    assert isinstance(bot_id, str)
    return bot_id


async def _agent(bot_id: str, status: str, title: str) -> str:
    from sevn.domain.session import open_session
    from sevn.store.models import Agent, Thread

    agent_id = mint_id("agent_")
    thread_id = mint_id("thread_")
    now = datetime.now(UTC)
    async with open_session() as session:
        session.add(
            Agent(
                id=agent_id,
                bot_id=bot_id,
                thread_id=thread_id,
                title=title,
                summary="",
                status=status,
                runtime="pydantic_ai",
                runtime_session_ref=None,
                origin_job_id=None,
                isolation="shared",
                created_at=now,
                last_activity_at=now,
            )
        )
        await session.flush()
        session.add(
            Thread(
                id=thread_id,
                bot_id=bot_id,
                agent_id=agent_id,
                kind="agent",
                summary="",
                summary_upto=None,
            )
        )
        await session.commit()
    return agent_id


async def _turn(
    agent_id: str,
    status: str,
    finished_at: datetime | None,
    reply: str | None = None,
) -> str:
    from sevn.domain.session import open_session
    from sevn.store.models import Agent, Message, Turn

    turn_id = mint_id("turn_")
    started = (finished_at or datetime.now(UTC)) - timedelta(seconds=5)
    async with open_session() as session:
        agent = await session.get(Agent, agent_id)
        assert agent is not None
        session.add(
            Turn(
                id=turn_id,
                agent_id=agent_id,
                thread_id=agent.thread_id,
                job_ids=[],
                status=status,
                model="test",
                usage={},
                model_messages=None,
                started_at=started,
                finished_at=finished_at,
            )
        )
        await session.flush()
        if reply is not None:
            session.add(
                Message(
                    id=mint_id("msg_"),
                    thread_id=agent.thread_id,
                    turn_id=turn_id,
                    agent_id=agent_id,
                    role="assistant",
                    author=agent.bot_id,
                    parts=[{"type": "text", "text": reply}],
                    created_at=finished_at or started,
                )
            )
        await session.commit()
    return turn_id


async def _pending(
    agent_id: str,
    turn_id: str,
    kind: str,
    payload: dict[str, object],
    created_at: datetime,
    status: str = "waiting",
) -> str:
    from sevn.domain.session import open_session
    from sevn.store.models import PendingRequest

    pending_id = mint_id("pend_")
    async with open_session() as session:
        session.add(
            PendingRequest(
                id=pending_id,
                turn_id=turn_id,
                agent_id=agent_id,
                kind=kind,
                tool_call_id=None,
                payload=payload,
                answer=None,
                status=status,
                created_at=created_at,
                resolved_at=None,
            )
        )
        await session.commit()
    return pending_id


async def _overview(client: object, **params: object) -> dict[str, Any]:
    frame, _earlier = await request(client, "fleet.overview", dict(params))
    return ok(frame)


def _load() -> None:
    load_modules("sevn.api.bots", "sevn.api.fleet")


async def test_empty_host_has_empty_panels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _load()
    async with connected(tmp_path, monkeypatch) as (_host, client):
        body = await _overview(client)
    assert body["bots"] == []
    assert body["waiting"] == []
    assert body["finished"] == []
    assert body["activity"] == []
    days = body["days"]
    assert len(days) == 14
    assert days[-1] == datetime.now(UTC).date().isoformat()
    assert days == sorted(days)
    as_of = datetime.fromisoformat(body["as_of"])
    assert abs((datetime.now(UTC) - as_of).total_seconds()) < 60


async def test_waiting_lists_every_open_request_oldest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _load()
    now = datetime.now(UTC)
    async with connected(tmp_path, monkeypatch) as (_host, client):
        first = await _bot(client, "Atlas")
        second = await _bot(client, "Nimbus")
        a = await _agent(first, "waiting", "Fix the build")
        b = await _agent(second, "waiting", "Draft the issue")
        turn_a = await _turn(a, "waiting", None)
        turn_b = await _turn(b, "waiting", None)
        newer = await _pending(
            a,
            turn_a,
            "approval",
            {"name": "shell.run", "args": {"command": "make test"}},
            now - timedelta(minutes=5),
        )
        older = await _pending(
            b,
            turn_b,
            "question",
            {"text": "Which subject line?", "name": "user.ask", "args": {"question": "x"}},
            now - timedelta(hours=30),
        )
        await _pending(
            a,
            turn_a,
            "approval",
            {"name": "shell.run", "args": {}},
            now - timedelta(hours=40),
            status="resolved",
        )
        body = await _overview(client)
    waiting = body["waiting"]
    assert [item["id"] for item in waiting] == [older, newer]
    question, approval = waiting
    assert question["kind"] == "question"
    assert question["text"] == "Which subject line?"
    assert question["bot_id"] == second
    assert question["bot_name"] == "Nimbus"
    assert question["agent_id"] == b
    assert question["agent_title"] == "Draft the issue"
    assert approval["kind"] == "approval"
    assert approval["name"] == "shell.run"
    assert approval["args"] == {"command": "make test"}
    assert approval["text"] == "shell.run"
    assert approval["turn_id"] == turn_a
    assert datetime.fromisoformat(question["created_at"]) < datetime.fromisoformat(
        approval["created_at"]
    )


async def test_finished_is_newest_first_with_failures_and_a_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _load()
    now = datetime.now(UTC)
    async with connected(tmp_path, monkeypatch) as (_host, client):
        bot = await _bot(client, "Atlas")
        agent = await _agent(bot, "idle", "Weekly scan")
        for index in range(22):
            await _turn(agent, "done", now - timedelta(hours=2, minutes=index), f"run {index}")
        failed = await _turn(agent, "failed", now - timedelta(minutes=1), "This turn failed.")
        await _turn(agent, "running", None)
        await _turn(agent, "waiting", None)
        body = await _overview(client)
    finished = body["finished"]
    assert len(finished) == 20
    assert finished[0]["turn_id"] == failed
    assert finished[0]["status"] == "failed"
    assert finished[0]["preview"] == "This turn failed."
    assert finished[1]["preview"] == "run 0"
    assert finished[1]["agent_title"] == "Weekly scan"
    assert finished[1]["bot_name"] == "Atlas"
    stamps = [datetime.fromisoformat(item["finished_at"]) for item in finished]
    assert stamps == sorted(stamps, reverse=True)
    assert {item["status"] for item in finished} <= {"done", "failed", "cancelled", "interrupted"}


async def test_finished_preview_is_the_first_line_and_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _load()
    now = datetime.now(UTC)
    async with connected(tmp_path, monkeypatch) as (_host, client):
        bot = await _bot(client, "Atlas")
        agent = await _agent(bot, "idle", "Report")
        await _turn(agent, "done", now, "\n\n" + "x" * 400 + "\nsecond line")
        await _turn(agent, "cancelled", now - timedelta(minutes=1))
        body = await _overview(client)
    first, second = body["finished"]
    assert first["preview"].startswith("x")
    assert "second line" not in first["preview"]
    assert len(first["preview"]) <= 160
    assert second["status"] == "cancelled"
    assert second["preview"] == ""


async def test_finished_can_be_filtered_by_bot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _load()
    now = datetime.now(UTC)
    async with connected(tmp_path, monkeypatch) as (_host, client):
        first = await _bot(client, "Atlas")
        second = await _bot(client, "Nimbus")
        a = await _agent(first, "idle", "A")
        b = await _agent(second, "idle", "B")
        await _turn(a, "done", now, "from atlas")
        for index in range(25):
            await _turn(b, "done", now - timedelta(seconds=index), "from nimbus")
        await _turn(a, "done", now - timedelta(days=3), "older atlas")
        body = await _overview(client, bot_id=first)
    assert [item["preview"] for item in body["finished"]] == ["from atlas", "older atlas"]
    assert {item["bot_id"] for item in body["finished"]} == {first}
    assert len(body["bots"]) == 2


async def test_activity_counts_done_turns_per_bot_and_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _load()
    now = datetime.now(UTC)
    today = now.date().isoformat()
    async with connected(tmp_path, monkeypatch) as (_host, client):
        bot = await _bot(client, "Atlas")
        quiet = await _bot(client, "Nimbus")
        agent = await _agent(bot, "idle", "A")
        await _turn(agent, "done", now, "a")
        await _turn(agent, "done", now - timedelta(seconds=30), "b")
        three_days = now - timedelta(days=3)
        await _turn(agent, "done", three_days, "c")
        await _turn(agent, "failed", now, "d")
        await _turn(agent, "done", now - timedelta(days=20), "too old")
        body = await _overview(client)
    activity = {(row["bot_id"], row["day"]): row["turns"] for row in body["activity"]}
    assert activity == {
        (bot, today): 2,
        (bot, three_days.date().isoformat()): 1,
    }
    assert all(row["bot_id"] != quiet for row in body["activity"])


async def test_bot_status_follows_its_busiest_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _load()
    now = datetime.now(UTC)
    async with connected(tmp_path, monkeypatch) as (_host, client):
        running = await _bot(client, "Runner")
        waiting = await _bot(client, "Waiter")
        idle = await _bot(client, "Idler")
        quiet = await _bot(client, "Quiet")
        await _agent(running, "running", "r")
        await _agent(running, "waiting", "w")
        asking = await _agent(waiting, "waiting", "q")
        await _agent(waiting, "idle", "i")
        await _agent(idle, "idle", "i")
        await _agent(idle, "done", "d")
        await _agent(quiet, "archived", "a")
        turn = await _turn(asking, "waiting", None)
        await _pending(asking, turn, "question", {"text": "ok?"}, now)
        body = await _overview(client)
    bots = {row["id"]: row for row in body["bots"]}
    assert bots[running]["status"] == "running"
    assert bots[running]["open_agents"] == 2
    assert bots[waiting]["status"] == "waiting"
    assert bots[waiting]["waiting"] == 1
    assert bots[idle]["status"] == "idle"
    assert bots[idle]["open_agents"] == 1
    assert bots[quiet]["status"] == "quiet"
    assert bots[quiet]["open_agents"] == 0
    assert bots[quiet]["name"] == "Quiet"
    assert [row["name"] for row in body["bots"]] == ["Runner", "Waiter", "Idler", "Quiet"]


async def test_overview_is_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _load()
    from sevn.contracts.methods import METHODS

    spec = METHODS["fleet.overview"]
    assert spec.mutating is False
    async with connected(tmp_path, monkeypatch) as (host, client):
        before = await host.outbox.since(0)
        await _overview(client)
        after = await host.outbox.since(0)
    assert len(after) == len(before)
