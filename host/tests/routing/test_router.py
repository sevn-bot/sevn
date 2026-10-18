"""Router actions, parallel agents, lifecycle, and reroute (green after W3)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fakes.fake_jev import FakeJev
from fakes.models import TurnGate, function_model
from support.canary import reset_model_requests
from support.chat import (
    connected,
    fetch_all,
    load_modules,
    mint_id,
    ok,
    poll_rows,
    request,
)

pytestmark = pytest.mark.xfail(
    reason="green after W3: jev router and parallel agents",
    strict=False,
)


async def _create_bot(client: object, **extra: object) -> dict[str, object]:
    frame, _earlier = await request(
        client,
        "bots.create",
        {"name": "Nimbus", "op_id": mint_id("op_"), **extra},
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


def _install(
    script: list[dict[str, object]],
    *,
    gate: TurnGate | None = None,
    pause: asyncio.Event | None = None,
) -> None:
    from sevn.decisions.jev import use_client
    from sevn.runtime.models import use_model

    use_client(FakeJev(script=script))
    use_model(function_model([{"kind": "text", "text": "ok"}], gate=gate, pause=pause))


def _clear() -> None:
    from sevn.decisions.jev import use_client
    from sevn.runtime.models import use_model

    use_client(None)
    use_model(None)


async def _quiet_worker() -> None:
    from sevn.runtime.worker import current

    worker = current()
    if worker is not None:
        await worker.aclose()


def _events(home: Path, kind: str) -> list[dict[str, object]]:
    rows = fetch_all(home, "SELECT type, payload FROM events WHERE type = ?", (kind,))
    return [dict(row) for row in rows]


async def test_new_request_spawns_agent_in_parallel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.worker import bind

    reset_model_requests()
    gate = TurnGate()
    load_modules("sevn.api.bots", "sevn.api.messages")
    _install(
        [
            {"message.intent": ("new_request", 0.95), "message.target_agent": ("none", 0.9)},
            {"message.intent": ("new_request", 0.96), "message.target_agent": ("none", 0.9)},
        ],
        gate=gate,
    )
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot = await _create_bot(client)
            first = await _send(client, bot["id"], "plan a trip to Lisbon")
            await gate.until(lambda: gate.active >= 1)
            second = await _send(client, bot["id"], "fix the invoice script")
            await gate.until(lambda: gate.active >= 2)
            assert second["agent_id"] != first["agent_id"]
            assert gate.max_active >= 2
            jobs = fetch_all(
                tmp_path,
                "SELECT agent_id, started_at, finished_at FROM jobs ORDER BY created_at",
            )
            assert len(jobs) == 2
            assert jobs[0]["started_at"] is not None
            assert jobs[1]["started_at"] is not None
            assert _parse_time(jobs[1]["started_at"]) < (
                _parse_time(jobs[0]["finished_at"])
                if jobs[0]["finished_at"] is not None
                else datetime.max.replace(tzinfo=UTC)
            )
    finally:
        gate.release_all.set()
        _clear()


async def test_follow_up_queues_on_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.runtime.worker import bind

    gate = TurnGate()
    load_modules("sevn.api.bots", "sevn.api.messages")
    _install(
        [
            {"message.intent": ("new_request", 0.95), "message.target_agent": ("none", 0.9)},
            {"message.intent": ("new_request", 0.95), "message.target_agent": ("none", 0.9)},
        ],
        gate=gate,
    )
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot = await _create_bot(client)
            first = await _send(client, bot["id"], "plan a trip")
            await gate.until(lambda: gate.active == 1)
            second = await _send(client, bot["id"], "fix the invoice", new_agent=True)
            await gate.until(lambda: gate.active == 2)
            gate.release_all.set()
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs",
                (),
                lambda rows: len(rows) == 2 and all(row["status"] == "done" for row in rows),
            )
            _clear()
            _install(
                [
                    {
                        "message.intent": ("follow_up", 0.95),
                        "message.target_agent": (str(first["agent_id"]), 0.93),
                    }
                ]
            )
            queued = await _send(client, bot["id"], "make the trip four days")
            assert queued["agent_id"] == first["agent_id"]
            assert queued["agent_id"] != second["agent_id"]
            await poll_rows(
                tmp_path,
                "SELECT agent_id, status FROM jobs WHERE id = ?",
                (queued["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
            )
    finally:
        gate.release_all.set()
        _clear()


async def test_steer_enqueues_into_running_pydantic_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.worker import bind
    from support.canary import model_request_payloads

    reset_model_requests()
    pause = asyncio.Event()
    load_modules("sevn.api.bots", "sevn.api.messages")
    _install(
        [{"message.intent": ("new_request", 0.95), "message.target_agent": ("none", 0.9)}],
        pause=pause,
    )
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot = await _create_bot(client)
            first = await _send(client, bot["id"], "draft the note")
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (first["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] == "started",
            )
            assert len(model_request_payloads()) == 1
            _clear()
            _install(
                [
                    {
                        "message.intent": ("steer", 0.95),
                        "message.target_agent": (str(first["agent_id"]), 0.94),
                        "busy.policy": ("steer", 0.92),
                    }
                ]
            )
            await _send(client, bot["id"], "steer-marker add a date")
            pause.set()
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (first["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
                timeout_s=3,
            )
            payloads = model_request_payloads()
            assert len(payloads) >= 2
            first_blob = str(payloads[0])
            later = "\n".join(str(item) for item in payloads[1:])
            assert "steer-marker" not in first_blob
            assert "steer-marker" in later
    finally:
        pause.set()
        _clear()


async def test_answer_resolves_pending_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.store.db import async_engine
    from sevn.store.models import PendingRequest
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from support.chat import insert_turn

    load_modules("sevn.api.bots", "sevn.api.messages")
    await _quiet_worker()
    async with connected(tmp_path, monkeypatch) as (_host, client):
        bot = await _create_bot(client)
        agent = await AgentService().spawn(bot_id=str(bot["id"]))
        await AgentService().set_status(agent.id, "waiting")
        job_id = mint_id("job_")
        turn_id = await insert_turn(
            tmp_path,
            agent_id=agent.id,
            thread_id=agent.thread_id,
            job_id=job_id,
            status="waiting",
            model_messages=[],
        )
        asked = datetime.now(UTC)
        engine = async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sevn.db'}")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        pending_id = mint_id("pend_")
        try:
            async with sessions() as session:
                session.add(
                    PendingRequest(
                        id=pending_id,
                        turn_id=turn_id,
                        agent_id=agent.id,
                        kind="question",
                        tool_call_id=None,
                        payload={"text": "Which day?"},
                        answer=None,
                        status="waiting",
                        created_at=asked,
                        resolved_at=None,
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()
        await _send(client, bot["id"], "Tuesday")
        rows = fetch_all(
            tmp_path,
            "SELECT status, answer FROM pending_requests WHERE id = ?",
            (pending_id,),
        )
        assert rows[0]["status"] == "resolved"
        assert "Tuesday" in str(rows[0]["answer"])
        revived = await AgentService().get(agent.id)
        assert revived.status != "waiting"


async def test_cancel_stops_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.domain.agents import AgentService
    from sevn.runtime.worker import bind

    gate = TurnGate()
    load_modules("sevn.api.bots", "sevn.api.messages")
    _install(
        [{"message.intent": ("new_request", 0.95), "message.target_agent": ("none", 0.9)}],
        gate=gate,
    )
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot = await _create_bot(client)
            first = await _send(client, bot["id"], "keep writing")
            await gate.until(lambda: gate.active == 1)
            _clear()
            _install(
                [
                    {
                        "message.intent": ("cancel", 0.97),
                        "message.target_agent": (str(first["agent_id"]), 0.96),
                        "busy.policy": ("interrupt", 0.9),
                    }
                ]
            )
            await _send(client, bot["id"], "stop")
            agent = await poll_agent(tmp_path, str(first["agent_id"]), "done")
            assert agent == "done"
            stopped = await AgentService().get(str(first["agent_id"]))
            assert stopped.status == "done"
    finally:
        gate.release_all.set()
        _clear()


async def poll_agent(home: Path, agent_id: str, status: str) -> str:
    rows = await poll_rows(
        home,
        "SELECT status FROM agents WHERE id = ?",
        (agent_id,),
        lambda found: bool(found) and found[0]["status"] == status,
    )
    return str(rows[0]["status"])


async def test_chit_chat_uses_toolless_ephemeral_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel
    from sevn.decisions.jev import use_client
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind

    tool_names: list[list[str]] = []

    async def respond(_messages: list[object], info: AgentInfo) -> ModelResponse:
        tool_names.append([tool.name for tool in info.function_tools])
        return ModelResponse(parts=[TextPart(content="hi there")])

    load_modules("sevn.api.bots", "sevn.api.messages")
    use_client(
        FakeJev(
            answers={
                "message.intent": ("chit_chat", 0.97),
                "message.target_agent": ("none", 0.9),
            }
        )
    )
    use_model(FunctionModel(respond, model_name="chit"))
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot = await _create_bot(client)
            sent = await _send(client, bot["id"], "good morning")
            await poll_agent(tmp_path, str(sent["agent_id"]), "done")
            assert tool_names
            assert tool_names[0] == []
    finally:
        _clear()


async def test_bot_cap_queues_new_agent_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.worker import bind

    gate = TurnGate()
    load_modules("sevn.api.bots", "sevn.api.messages")
    home_config = '[secrets]\nbackend = "age-file"\n\n[bots]\nmax_parallel_agents = 1\n'
    (tmp_path / "config.toml").write_text(home_config, encoding="utf-8")
    monkeypatch.setenv("SEVN_BOTS__MAX_PARALLEL_AGENTS", "1")
    _install(
        [
            {"message.intent": ("new_request", 0.95), "message.target_agent": ("none", 0.9)},
            {"message.intent": ("new_request", 0.95), "message.target_agent": ("none", 0.9)},
        ],
        gate=gate,
    )
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot = await _create_bot(client)
            await _send(client, bot["id"], "first task")
            await gate.until(lambda: gate.active == 1)
            await _send(client, bot["id"], "second task")
            await asyncio.sleep(0.05)
            assert gate.active == 1
            assert gate.max_active == 1
            queued = fetch_all(
                tmp_path,
                "SELECT status, agent_id FROM jobs ORDER BY created_at",
            )
            assert len(queued) == 2
            assert queued[1]["status"] == "queued"
            notices = _events(tmp_path, "job.queued")
            assert any(_ahead(row) == 1 for row in notices)
    finally:
        gate.release_all.set()
        _clear()


def _ahead(row: dict[str, object]) -> object:
    payload = row.get("payload")
    if isinstance(payload, str):
        parsed = json.loads(payload)
        payload = parsed if isinstance(parsed, dict) else {}
    if not isinstance(payload, dict):
        return None
    if payload.get("ahead") is not None:
        return payload.get("ahead")
    notice = str(payload.get("notice") or "")
    if notice == "queued: 1 ahead":
        return 1
    return None


async def test_sibling_list_in_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.runtime.worker import bind
    from support.canary import model_request_payloads

    reset_model_requests()
    load_modules("sevn.api.bots", "sevn.api.messages")
    _install([{"message.intent": ("new_request", 0.95), "message.target_agent": ("none", 0.9)}])
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot = await _create_bot(client)
            siblings: list[str] = []
            for index in range(11):
                agent = await AgentService().spawn(bot_id=str(bot["id"]))
                title = f"SIB-{index:02d}"
                siblings.append(title)
                with sqlite3.connect(tmp_path / "sevn.db") as connection:
                    connection.execute(
                        """
                        UPDATE agents
                        SET title = ?, status = 'idle', summary = 'sibling'
                        WHERE id = ?
                        """,
                        (title, agent.id),
                    )
                    connection.commit()
            sent = await _send(client, bot["id"], "do the current task")
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (sent["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
            )
            blob = "\n".join(
                str(item.get("instructions") or "") for item in model_request_payloads()
            )
            present = [title for title in siblings if title in blob]
            assert len(present) == 10
            assert "idle" in blob
    finally:
        _clear()


async def test_idle_ttl_to_done_then_archived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from freezegun import freeze_time
    from sevn.domain.agents import expire_agents
    from sevn.runtime.worker import bind

    load_modules("sevn.api.bots", "sevn.api.messages")
    start = datetime(2026, 6, 1, tzinfo=UTC)
    _install([{"message.intent": ("new_request", 0.95), "message.target_agent": ("none", 0.9)}])
    try:
        with freeze_time(start) as frozen:
            async with connected(tmp_path, monkeypatch) as (host, client):
                bind(host.hub)
                bot = await _create_bot(client)
                sent = await _send(client, bot["id"], "one note")
                await poll_agent(tmp_path, str(sent["agent_id"]), "idle")
                frozen.move_to(start + timedelta(hours=24, seconds=1))
                await expire_agents()
                assert await poll_agent(tmp_path, str(sent["agent_id"]), "done") == "done"
                frozen.move_to(
                    start + timedelta(hours=24, seconds=1) + timedelta(days=7, seconds=1)
                )
                await expire_agents()
                assert await poll_agent(tmp_path, str(sent["agent_id"]), "archived") == "archived"
    finally:
        _clear()


async def test_follow_up_revives_archived_agent_same_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.runtime.worker import bind

    load_modules("sevn.api.bots", "sevn.api.messages")
    _install([{"message.intent": ("new_request", 0.95), "message.target_agent": ("none", 0.9)}])
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot = await _create_bot(client)
            agent = await AgentService().spawn(bot_id=str(bot["id"]))
            thread_id = agent.thread_id
            with sqlite3.connect(tmp_path / "sevn.db") as connection:
                connection.execute(
                    "UPDATE agents SET status = 'archived', title = 'Invoice fix' WHERE id = ?",
                    (agent.id,),
                )
                connection.commit()
            _clear()
            _install(
                [
                    {
                        "message.intent": ("follow_up", 0.95),
                        "message.target_agent": (agent.id, 0.93),
                    }
                ]
            )
            sent = await _send(client, bot["id"], "add the receipt", agent_id=agent.id)
            assert sent["agent_id"] == agent.id
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (sent["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
            )
            revived = await AgentService().get(agent.id)
            assert revived.thread_id == thread_id
            assert revived.status in {"idle", "running", "waiting"}
            stored = fetch_all(
                tmp_path,
                "SELECT thread_id, archived_at, status FROM agents WHERE id = ?",
                (agent.id,),
            )
            assert stored[0]["thread_id"] == thread_id
            assert stored[0]["archived_at"] is None
    finally:
        _clear()


async def test_reroute_before_start_moves_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService

    load_modules("sevn.api.bots", "sevn.api.messages")
    await _quiet_worker()
    async with connected(tmp_path, monkeypatch) as (_host, client):
        bot = await _create_bot(client)
        target = await AgentService().spawn(bot_id=str(bot["id"]))
        sent = await _send(client, bot["id"], "put this on the invoice")
        message_id = _user_message_id(tmp_path, "put this on the invoice")
        moved, _earlier = await request(
            client,
            "messages.reroute",
            {
                "message_id": message_id,
                "agent_id": target.id,
                "op_id": mint_id("op_"),
            },
        )
        assert ok(moved)["agent_id"] == target.id
        jobs = fetch_all(
            tmp_path,
            "SELECT agent_id, status, started_at FROM jobs WHERE id = ?",
            (sent["job_id"],),
        )
        assert jobs[0]["agent_id"] == target.id
        assert jobs[0]["status"] == "queued"
        assert jobs[0]["started_at"] is None
        assert _events(tmp_path, "route.corrected")
        corrected = fetch_all(
            tmp_path,
            "SELECT corrected_to FROM decision_log WHERE corrected_to IS NOT NULL",
        )
        assert any(row["corrected_to"] == target.id for row in corrected)


async def test_reroute_new_starts_another_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_modules("sevn.api.bots", "sevn.api.messages")
    await _quiet_worker()
    async with connected(tmp_path, monkeypatch) as (_host, client):
        bot = await _create_bot(client)
        sent = await _send(client, bot["id"], "start this elsewhere")
        message_id = _user_message_id(tmp_path, "start this elsewhere")
        moved, _earlier = await request(
            client,
            "messages.reroute",
            {"message_id": message_id, "new": True, "op_id": mint_id("op_")},
        )
        body = ok(moved)
        assert body["agent_id"] != sent["agent_id"]
        jobs = fetch_all(
            tmp_path,
            "SELECT agent_id, status FROM jobs WHERE id = ?",
            (sent["job_id"],),
        )
        assert jobs[0]["agent_id"] == body["agent_id"]
        assert jobs[0]["status"] == "queued"
        assert _events(tmp_path, "route.corrected")


async def test_reroute_while_running_cancels_and_requeues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.runtime.worker import bind

    gate = TurnGate()
    load_modules("sevn.api.bots", "sevn.api.messages")
    _install(
        [{"message.intent": ("new_request", 0.95), "message.target_agent": ("none", 0.9)}],
        gate=gate,
    )
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot = await _create_bot(client)
            target = await AgentService().spawn(bot_id=str(bot["id"]))
            sent = await _send(client, bot["id"], "write the long draft")
            await gate.until(lambda: gate.active == 1)
            message_id = _user_message_id(tmp_path, "write the long draft")
            moved, _earlier = await request(
                client,
                "messages.reroute",
                {"message_id": message_id, "agent_id": target.id, "op_id": mint_id("op_")},
            )
            body = ok(moved)
            assert body["agent_id"] == target.id
            jobs = await poll_rows(
                tmp_path,
                "SELECT agent_id, status FROM jobs WHERE id = ?",
                (sent["job_id"],),
                lambda rows: (
                    bool(rows)
                    and rows[0]["agent_id"] == target.id
                    and rows[0]["status"] == "queued"
                ),
            )
            assert jobs[0]["status"] == "queued"
            turns = fetch_all(
                tmp_path,
                "SELECT status FROM turns WHERE agent_id = ?",
                (sent["agent_id"],),
            )
            assert turns
            assert turns[0]["status"] == "cancelled"
            assert _events(tmp_path, "route.corrected")
    finally:
        gate.release_all.set()
        _clear()


def _user_message_id(home: Path, text: str) -> str:
    rows = fetch_all(home, "SELECT id, parts, role FROM messages")
    for row in rows:
        if row["role"] != "user":
            continue
        if text in str(row["parts"]):
            return str(row["id"])
    raise AssertionError(f"no user message containing {text!r}")
