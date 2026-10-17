"""Per-agent lock, host cap, crash recovery, snapshot, and cancel."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest
from fakes.models import TurnGate, function_model
from support.chat import (
    connected,
    fetch_all,
    insert_job,
    insert_turn,
    load_modules,
    mint_id,
    ok,
    poll_rows,
    request,
)


async def _create_bot(client: object) -> dict[str, object]:
    frame, _earlier = await request(
        client,
        "bots.create",
        {"name": "Nimbus", "op_id": mint_id("op_")},
    )
    return ok(frame)


async def _send(client: object, bot_id: object, text: str, **extra: object) -> dict[str, object]:
    frame, _earlier = await request(
        client,
        "messages.send",
        {"bot_id": bot_id, "text": text, "op_id": mint_id("op_"), **extra},
    )
    return ok(frame)


def _parse_time(value: object) -> datetime:
    assert isinstance(value, str)
    return datetime.fromisoformat(value)


async def test_one_turn_per_agent_at_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind

    gate = TurnGate()
    use_model(function_model([{"kind": "text", "text": "ok"}], gate=gate))
    load_modules("sevn.api.bots", "sevn.api.messages")
    async with connected(tmp_path, monkeypatch) as (host, client):
        bind(host.hub)
        bot = await _create_bot(client)
        first = await _send(client, bot["id"], "one")
        await gate.until(lambda: gate.active == 1)
        second = await _send(client, bot["id"], "two")
        await asyncio.sleep(0.05)
        assert gate.active == 1
        assert gate.max_active == 1
        assert second["agent_id"] == first["agent_id"]
        gate.release_all.set()
        await gate.until(lambda: gate.active == 0)
        assert gate.max_active == 1
        jobs = await poll_rows(
            tmp_path,
            "SELECT started_at, finished_at FROM jobs ORDER BY created_at",
            (),
            lambda rows: len(rows) == 2 and all(row["finished_at"] for row in rows),
        )
        assert _parse_time(jobs[0]["finished_at"]) <= _parse_time(jobs[1]["started_at"])


async def test_max_running_turns_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind

    gate = TurnGate()
    use_model(function_model([{"kind": "text", "text": "ok"}], gate=gate))
    load_modules("sevn.api.bots", "sevn.api.messages")
    async with connected(tmp_path, monkeypatch) as (host, client):
        bind(host.hub)
        bot = await _create_bot(client)
        await _send(client, bot["id"], "a0")
        for index in range(1, 4):
            await _send(client, bot["id"], f"a{index}", new_agent=True)
        await gate.until(lambda: gate.active == 3)
        await asyncio.sleep(0.05)
        assert gate.active == 3
        assert gate.max_active == 3
        gate.release_all.set()
        await gate.until(lambda: gate.active == 0)
        assert gate.max_active == 3
        agents = fetch_all(tmp_path, "SELECT id FROM agents")
        assert len(agents) == 4


async def test_restart_requeues_started_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.runtime.models import use_model
    from sevn.runtime.recovery import recover
    from sevn.runtime.worker import bind

    load_modules("sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (host, client):
        bot = await _create_bot(client)
        agent = await AgentService().spawn(bot_id=str(bot["id"]))
        started = await insert_job(
            tmp_path,
            bot_id=str(bot["id"]),
            agent_id=agent.id,
            text="crashed",
            status="started",
        )
        await insert_turn(
            tmp_path,
            agent_id=agent.id,
            thread_id=agent.thread_id,
            job_id=started,
            status="running",
            model_messages=None,
        )
        waiting_agent = await AgentService().spawn(bot_id=str(bot["id"]))
        waiting_job = await insert_job(
            tmp_path,
            bot_id=str(bot["id"]),
            agent_id=waiting_agent.id,
            text="paused",
            status="started",
        )
        await insert_turn(
            tmp_path,
            agent_id=waiting_agent.id,
            thread_id=waiting_agent.thread_id,
            job_id=waiting_job,
            status="waiting",
            model_messages=[],
        )
        await recover()
        started_rows = fetch_all(tmp_path, "SELECT status FROM jobs WHERE id = ?", (started,))
        assert started_rows[0]["status"] == "queued"
        waiting_turn = fetch_all(
            tmp_path,
            "SELECT status FROM turns WHERE agent_id = ?",
            (waiting_agent.id,),
        )
        assert waiting_turn[0]["status"] == "waiting"
        waiting_job_row = fetch_all(
            tmp_path, "SELECT status FROM jobs WHERE id = ?", (waiting_job,)
        )
        assert waiting_job_row[0]["status"] != "queued"
        use_model(function_model([{"kind": "text", "text": "done"}]))
        worker = bind(host.hub)
        worker.kick(agent.id)
        await poll_rows(
            tmp_path,
            "SELECT status FROM jobs WHERE id = ?",
            (started,),
            lambda rows: bool(rows) and rows[0]["status"] == "done",
        )


async def test_turns_snapshot_returns_partial_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind

    pause = asyncio.Event()
    use_model(function_model([{"kind": "text", "text": "hello"}], pause=pause))
    load_modules("sevn.api.bots", "sevn.api.messages")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot = await _create_bot(client)
            await _send(client, bot["id"], "hi")
            turns = await poll_rows(
                tmp_path,
                "SELECT id FROM turns",
                (),
                lambda rows: bool(rows),
            )
            turn_id = turns[0]["id"]
            text = ""
            status = ""
            for _ in range(50):
                frame, _earlier = await request(client, "turns.snapshot", {"turn_id": turn_id})
                body = ok(frame)
                text = str(body.get("text") or "")
                status = str(body.get("status") or "")
                if "hello" in text:
                    break
                await asyncio.sleep(0.02)
            assert "hello" in text
            assert status != "done"
    finally:
        pause.set()


async def test_turns_cancel_stops_turn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.runtime.models import use_model
    from sevn.runtime.runtimes.pydantic_ai import PydanticAIRuntime
    from sevn.runtime.worker import bind

    pause = asyncio.Event()
    called: list[str] = []

    async def spy(self: object, agent_id: str) -> None:
        called.append(agent_id)
        pause.set()

    monkeypatch.setattr(PydanticAIRuntime, "interrupt", spy)
    use_model(function_model([{"kind": "text", "text": "hello"}], pause=pause))
    load_modules("sevn.api.bots", "sevn.api.messages")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot = await _create_bot(client)
            await _send(client, bot["id"], "hi")
            turns = await poll_rows(
                tmp_path,
                "SELECT id FROM turns",
                (),
                lambda rows: bool(rows),
            )
            turn_id = turns[0]["id"]
            frame, _earlier = await request(
                client,
                "turns.cancel",
                {"turn_id": turn_id, "op_id": mint_id("op_")},
            )
            ok(frame)
            assert called
            await poll_rows(
                tmp_path,
                "SELECT status FROM turns WHERE id = ?",
                (turn_id,),
                lambda rows: bool(rows) and rows[0]["status"] == "cancelled",
            )
    finally:
        pause.set()


_PROVIDER_CANARY = "provider-echo-CANARY-9f3a"
_FAILED_TEXT = "This turn failed."


def _raising_model(message: str) -> object:
    from collections.abc import AsyncIterator

    from pydantic_ai.models.function import FunctionModel

    async def respond(_messages: list[object], _info: object) -> object:
        raise RuntimeError(message)

    async def stream(_messages: list[object], _info: object) -> AsyncIterator[str]:
        if _messages is not None or _info is not None:
            raise RuntimeError(message)
        yield ""

    return FunctionModel(respond, stream_function=stream, model_name="raising")


def _stored_rows(home: Path) -> str:
    chunks: list[str] = []
    for sql in (
        "SELECT * FROM messages",
        "SELECT * FROM events",
        "SELECT * FROM jobs",
        "SELECT * FROM turns",
    ):
        chunks.append(json.dumps([dict(row) for row in fetch_all(home, sql)], default=str))
    return "\n".join(chunks)


async def test_provider_error_after_start_fails_turn_without_storing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A turn that raises after it starts fails closed and hides the provider text."""
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind

    use_model(_raising_model(_PROVIDER_CANARY))
    load_modules("sevn.api.bots", "sevn.api.messages")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot = await _create_bot(client)
            await _send(client, bot["id"], "fail this turn")
            await poll_rows(
                tmp_path,
                "SELECT status FROM turns",
                (),
                lambda rows: bool(rows) and rows[0]["status"] == "failed",
            )
            turns = fetch_all(tmp_path, "SELECT status, model_messages FROM turns")
            assert len(turns) == 1
            assert turns[0]["status"] == "failed"
            raw_messages = turns[0]["model_messages"]
            parsed: object = None if raw_messages is None else json.loads(str(raw_messages))
            assert parsed is None
            agents = fetch_all(tmp_path, "SELECT status FROM agents")
            assert agents[0]["status"] == "idle"
            jobs = fetch_all(tmp_path, "SELECT status FROM jobs")
            assert jobs[0]["status"] == "failed"
            listed, _earlier = await request(client, "messages.list", {"bot_id": bot["id"]})
            body = ok(listed)
            messages = body["messages"]
            assert isinstance(messages, list)
            assistant = [
                part["text"]
                for message in messages
                if isinstance(message, dict) and message.get("role") == "assistant"
                for part in message["parts"]
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            ]
            assert assistant == [_FAILED_TEXT]
            assert _PROVIDER_CANARY not in _stored_rows(tmp_path)
            assert _PROVIDER_CANARY not in json.dumps(body)
    finally:
        use_model(None)
