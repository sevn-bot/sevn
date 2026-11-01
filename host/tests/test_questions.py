"""Phase 3: questions with options, priority, a due time and a blocking flag."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fakes.models import function_model
from support.canary import model_request_payloads, reset_model_requests
from support.chat import (
    connected,
    fetch_all,
    insert_turn,
    load_modules,
    mint_id,
    ok,
    poll_rows,
    request,
)


async def _lane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, str]:
    from sevn.domain.agents import AgentService
    from sevn.domain.bots import BotService
    from support.botcore import arm_configured, upgrade_home

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Nimbus")
    agent = await AgentService().spawn(bot.id)
    turn_id = await insert_turn(
        tmp_path,
        agent_id=agent.id,
        thread_id=agent.thread_id,
        job_id=mint_id("job_"),
        status="running",
        model_messages=[],
    )
    return bot, agent, turn_id


def _payload(home: Path, pending_id: str) -> dict[str, Any]:
    rows = fetch_all(home, "SELECT payload FROM pending_requests WHERE id = ?", (pending_id,))
    loaded = json.loads(rows[0]["payload"])
    assert isinstance(loaded, dict)
    return loaded


async def test_ask_stores_options_priority_due_and_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.tools.user import ask

    _bot, agent, turn_id = await _lane(tmp_path, monkeypatch)
    due = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    pending_id = await ask(
        agent.id,
        turn_id,
        "Which subject line?",
        options=["Is your fleet out of control?", "Three dashboards"],
        priority="high",
        due_by=due,
        blocking=False,
    )
    payload = _payload(tmp_path, pending_id)
    assert payload["text"] == "Which subject line?"
    assert payload["options"] == [
        {"id": "opt_1", "label": "Is your fleet out of control?"},
        {"id": "opt_2", "label": "Three dashboards"},
    ]
    assert payload["priority"] == "high"
    assert datetime.fromisoformat(payload["due_by"]) == datetime.fromisoformat(due)
    assert payload["blocking"] is False


async def test_ask_defaults_and_refusals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.domain.errors import DomainError
    from sevn.tools.user import ask

    _bot, agent, turn_id = await _lane(tmp_path, monkeypatch)
    pending_id = await ask(agent.id, turn_id, "Which day?")
    payload = _payload(tmp_path, pending_id)
    assert payload["options"] == []
    assert payload["priority"] == "normal"
    assert payload["due_by"] is None
    assert payload["blocking"] is True
    for kwargs in (
        {"due_by": "tomorrow"},
        {"due_by": "2026-11-02T10:00:00"},
        {"priority": "urgent"},
        {"options": ["a"] * 7},
        {"options": ["ok", " "]},
    ):
        with pytest.raises(DomainError) as caught:
            await ask(agent.id, turn_id, "Which day?", **kwargs)
        assert caught.value.code == "invalid_params"


def _install(question: dict[str, object]) -> None:
    from fakes.fake_jev import FakeJev
    from sevn.decisions.jev import use_client
    from sevn.runtime.models import use_model

    use_client(FakeJev(answers={}))
    use_model(
        function_model(
            [
                [{"kind": "tool", "name": "user.ask", "args": question}],
                [{"kind": "text", "text": "asked"}],
                [{"kind": "text", "text": "thanks"}],
            ]
        )
    )


def _clear() -> None:
    from sevn.decisions.jev import use_client
    from sevn.runtime.models import use_model

    use_client(None)
    use_model(None)


async def _asked(client: Any, home: Path) -> tuple[dict[str, Any], str]:
    frame, _earlier = await request(
        client, "bots.create", {"name": "Nimbus", "op_id": mint_id("op_")}
    )
    bot = ok(frame)
    frame, _earlier = await request(
        client,
        "messages.send",
        {"bot_id": bot["id"], "text": "plan the issue", "op_id": mint_id("op_")},
    )
    sent = ok(frame)
    await poll_rows(
        home,
        "SELECT status FROM turns WHERE agent_id = ? AND status = 'waiting'",
        (sent["agent_id"],),
        lambda rows: bool(rows),
    )
    rows = fetch_all(
        home,
        "SELECT id FROM pending_requests WHERE agent_id = ? AND status = 'waiting'",
        (sent["agent_id"],),
    )
    return sent, str(rows[0]["id"])


async def _answered_run(home: Path, agent_id: str, job_id: str) -> None:
    await poll_rows(
        home,
        "SELECT status FROM jobs WHERE id = ?",
        (job_id,),
        lambda rows: bool(rows) and rows[0]["status"] == "done",
    )
    rows = fetch_all(home, "SELECT agent_id FROM jobs WHERE id = ?", (job_id,))
    assert rows[0]["agent_id"] == agent_id


async def test_answer_a_question_with_an_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.worker import bind

    reset_model_requests()
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    _install({"question": "Which subject?", "options": ["Short", "Long"], "priority": "high"})
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            sent, pending_id = await _asked(client, tmp_path)
            frame, _earlier = await request(
                client,
                "pending.answer",
                {"pending_id": pending_id, "option_id": "opt_2", "op_id": mint_id("op_")},
            )
            body = ok(frame)
            assert body["id"] == pending_id
            assert body["status"] == "resolved"
            assert isinstance(body["job_id"], str)
            await _answered_run(tmp_path, sent["agent_id"], body["job_id"])
            rows = fetch_all(
                tmp_path, "SELECT status, answer FROM pending_requests WHERE id = ?", (pending_id,)
            )
            assert rows[0]["status"] == "resolved"
            assert json.loads(rows[0]["answer"]) == {"option_id": "opt_2", "text": "Long"}
            waiting = fetch_all(
                tmp_path,
                "SELECT id FROM turns WHERE agent_id = ? AND status = 'waiting'",
                (sent["agent_id"],),
            )
            assert waiting == []
            later = "\n".join(str(item) for item in model_request_payloads()[2:])
            assert "Long" in later
            stored = await host.outbox.since(0)
            assert any(
                row.type == "pending.resolved" and row.payload.get("pending_id") == pending_id
                for row in stored
            )
    finally:
        _clear()


async def test_answer_a_question_with_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.runtime.worker import bind

    reset_model_requests()
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    _install({"question": "Which day?"})
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            sent, pending_id = await _asked(client, tmp_path)
            frame, _earlier = await request(
                client,
                "pending.answer",
                {"pending_id": pending_id, "text": "Tuesday at 10", "op_id": mint_id("op_")},
            )
            body = ok(frame)
            await _answered_run(tmp_path, sent["agent_id"], body["job_id"])
            rows = fetch_all(
                tmp_path, "SELECT answer FROM pending_requests WHERE id = ?", (pending_id,)
            )
            assert json.loads(rows[0]["answer"]) == {"text": "Tuesday at 10"}
            later = "\n".join(str(item) for item in model_request_payloads()[2:])
            assert "Tuesday at 10" in later
    finally:
        _clear()


async def test_bad_answers_are_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.runtime.worker import bind

    reset_model_requests()
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    _install({"question": "Which subject?", "options": ["Short", "Long"]})
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            _sent, pending_id = await _asked(client, tmp_path)
            for params in (
                {"option_id": "opt_9"},
                {"answer": "approve"},
                {},
                {"text": "   "},
                {"option_id": "opt_1", "text": "both"},
            ):
                frame, _earlier = await request(
                    client,
                    "pending.answer",
                    {"pending_id": pending_id, "op_id": mint_id("op_"), **params},
                )
                assert frame.get("e", {}).get("code") == "invalid_params", (params, frame)
            rows = fetch_all(
                tmp_path, "SELECT status FROM pending_requests WHERE id = ?", (pending_id,)
            )
            assert rows[0]["status"] == "waiting"
    finally:
        _clear()


async def test_an_approval_still_takes_approve_or_deny(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_modules("sevn.api.pending")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        frame, _earlier = await request(
            client,
            "pending.answer",
            {"pending_id": "pend_missing", "option_id": "opt_1", "op_id": mint_id("op_")},
        )
        assert frame.get("e", {}).get("code") in {"not_found", "invalid_params"}


async def test_cancelling_the_turn_expires_its_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.worker import bind

    reset_model_requests()
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    _install({"question": "Which day?"})
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            sent, pending_id = await _asked(client, tmp_path)
            turn = fetch_all(
                tmp_path,
                "SELECT id FROM turns WHERE agent_id = ? AND status = 'waiting'",
                (sent["agent_id"],),
            )
            frame, _earlier = await request(
                client, "turns.cancel", {"turn_id": turn[0]["id"], "op_id": mint_id("op_")}
            )
            ok(frame)
            rows = fetch_all(
                tmp_path, "SELECT status, answer FROM pending_requests WHERE id = ?", (pending_id,)
            )
            assert rows[0]["status"] == "resolved"
            assert json.loads(rows[0]["answer"]) == {"expired": True}
    finally:
        _clear()


async def test_fleet_cards_sort_by_blocking_priority_then_age(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.domain.bots import BotService
    from sevn.domain.session import open_session
    from sevn.store.models import PendingRequest

    load_modules("sevn.api.fleet")
    now = datetime.now(UTC)
    async with connected(tmp_path, monkeypatch) as (_host, client):
        bot = await BotService().create("Nimbus")
        agent = await AgentService().spawn(bot.id)
        turn_id = await insert_turn(
            tmp_path,
            agent_id=agent.id,
            thread_id=agent.thread_id,
            job_id=mint_id("job_"),
            status="waiting",
            model_messages=[],
        )

        def question(
            text: str, age_h: int, *, priority: str, blocking: bool, due: datetime | None = None
        ) -> PendingRequest:
            return PendingRequest(
                id=mint_id("pend_"),
                turn_id=turn_id,
                agent_id=agent.id,
                kind="question",
                tool_call_id=None,
                payload={
                    "text": text,
                    "name": "user.ask",
                    "args": {"question": text},
                    "options": [{"id": "opt_1", "label": "Yes"}],
                    "priority": priority,
                    "due_by": None if due is None else due.isoformat(),
                    "blocking": blocking,
                },
                answer=None,
                status="waiting",
                created_at=now - timedelta(hours=age_h),
                resolved_at=None,
            )

        due = now + timedelta(hours=2)
        async with open_session() as session:
            session.add_all(
                [
                    question("fyi old", 50, priority="high", blocking=False),
                    question("blocking low", 40, priority="low", blocking=True),
                    question("blocking high new", 1, priority="high", blocking=True, due=due),
                    question("blocking high old", 5, priority="high", blocking=True),
                    question("blocking normal", 30, priority="normal", blocking=True),
                    PendingRequest(
                        id=mint_id("pend_"),
                        turn_id=turn_id,
                        agent_id=agent.id,
                        kind="approval",
                        tool_call_id="call_1",
                        payload={"name": "shell", "args": {"command": "make test"}},
                        answer=None,
                        status="waiting",
                        created_at=now - timedelta(hours=10),
                        resolved_at=None,
                    ),
                ]
            )
            await session.commit()
        frame, _earlier = await request(client, "fleet.overview", {})
        waiting = ok(frame)["waiting"]
    texts = [item["text"] for item in waiting]
    assert texts == [
        "blocking high old",
        "blocking high new",
        "blocking normal",
        "shell",
        "blocking low",
        "fyi old",
    ]
    first = waiting[1]
    assert first["priority"] == "high"
    assert first["blocking"] is True
    assert first["options"] == [{"id": "opt_1", "label": "Yes"}]
    assert datetime.fromisoformat(first["due_by"]) == due
    approval = waiting[3]
    assert approval["priority"] == "normal"
    assert approval["blocking"] is True
    assert approval["options"] == []
    assert approval["due_by"] is None
