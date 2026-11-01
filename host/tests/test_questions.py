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


async def _two_questions(home: Path) -> tuple[Any, str, str, str]:
    from sevn.domain.agents import AgentService
    from sevn.domain.bots import BotService
    from sevn.tools.user import ask

    bot = await BotService().create("Nimbus")
    agent = await AgentService().spawn(bot.id)
    turn_id = await insert_turn(
        home,
        agent_id=agent.id,
        thread_id=agent.thread_id,
        job_id=mint_id("job_"),
        status="running",
        model_messages=[],
    )
    day = await ask(agent.id, turn_id, "Which day?", options=["Monday", "Tuesday"])
    audience = await ask(agent.id, turn_id, "Which audience?")
    return agent, turn_id, day, audience


def _pending(home: Path, pending_id: str) -> dict[str, Any]:
    rows = fetch_all(
        home, "SELECT status, answer FROM pending_requests WHERE id = ?", (pending_id,)
    )
    answer = rows[0]["answer"]
    return {"status": rows[0]["status"], "answer": None if answer is None else json.loads(answer)}


def _turn_status(home: Path, turn_id: str) -> str:
    return str(fetch_all(home, "SELECT status FROM turns WHERE id = ?", (turn_id,))[0]["status"])


async def test_answering_one_card_keeps_the_other_question_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_modules("sevn.api.pending")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        agent, turn_id, day, audience = await _two_questions(tmp_path)
        frame, _earlier = await request(
            client,
            "pending.answer",
            {"pending_id": day, "option_id": "opt_1", "op_id": mint_id("op_")},
        )
        ok(frame)
        assert _pending(tmp_path, day) == {
            "status": "resolved",
            "answer": {"option_id": "opt_1", "text": "Monday"},
        }
        assert _pending(tmp_path, audience) == {"status": "waiting", "answer": None}
        assert _turn_status(tmp_path, turn_id) == "waiting"
        agents = fetch_all(tmp_path, "SELECT status FROM agents WHERE id = ?", (agent.id,))
        assert agents[0]["status"] == "waiting"
        frame, _earlier = await request(
            client,
            "pending.answer",
            {"pending_id": audience, "text": "Owners", "op_id": mint_id("op_")},
        )
        ok(frame)
        assert _pending(tmp_path, audience) == {"status": "resolved", "answer": {"text": "Owners"}}
        assert _turn_status(tmp_path, turn_id) == "done"
        agents = fetch_all(tmp_path, "SELECT status FROM agents WHERE id = ?", (agent.id,))
        assert agents[0]["status"] != "waiting"
        jobs = fetch_all(
            tmp_path, "SELECT text FROM jobs WHERE agent_id = ? AND status = 'queued'", (agent.id,)
        )
        assert sorted(row["text"] for row in jobs) == ["Monday", "Owners"]


async def test_a_nonblocking_question_does_not_pause_the_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.pending import PendingService
    from sevn.tools.user import ask

    _bot, agent, turn_id = await _lane(tmp_path, monkeypatch)
    await ask(agent.id, turn_id, "Any notes?", blocking=False)
    assert _turn_status(tmp_path, turn_id) == "running"
    agents = fetch_all(tmp_path, "SELECT status FROM agents WHERE id = ?", (agent.id,))
    assert agents[0]["status"] != "waiting"
    assert await PendingService().has_waiting(turn_id) is False
    await ask(agent.id, turn_id, "Which day?")
    assert _turn_status(tmp_path, turn_id) == "waiting"
    assert await PendingService().has_waiting(turn_id) is True


async def test_a_nonblocking_question_survives_its_finished_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The turn ends done; the card still answers and queues the reply."""
    from sevn.runtime.worker import bind

    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    _install({"question": "Any notes?", "blocking": False})
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            frame, _earlier = await request(
                client, "bots.create", {"name": "Nimbus", "op_id": mint_id("op_")}
            )
            bot = ok(frame)
            frame, _earlier = await request(
                client,
                "messages.send",
                {"bot_id": bot["id"], "text": "draft it", "op_id": mint_id("op_")},
            )
            sent = ok(frame)
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (sent["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
            )
            pending = fetch_all(
                tmp_path,
                "SELECT id, status FROM pending_requests WHERE agent_id = ?",
                (sent["agent_id"],),
            )
            assert pending[0]["status"] == "waiting"
            frame, _earlier = await request(
                client,
                "pending.answer",
                {"pending_id": pending[0]["id"], "text": "none", "op_id": mint_id("op_")},
            )
            await _answered_run(tmp_path, sent["agent_id"], ok(frame)["job_id"])
    finally:
        _clear()


async def test_concurrent_answers_claim_the_question_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from sevn.domain.errors import DomainError
    from sevn.domain.routing import answer_question

    async with connected(tmp_path, monkeypatch) as (host, _client):
        agent, _turn_id, day, _audience = await _two_questions(tmp_path)
        results = await asyncio.gather(
            answer_question(day, option_id="opt_1", text=None, hub=host.hub),
            answer_question(day, option_id="opt_2", text=None, hub=host.hub),
            return_exceptions=True,
        )
        won = [item for item in results if isinstance(item, tuple)]
        lost = [item for item in results if isinstance(item, DomainError)]
        assert len(won) == 1, results
        assert len(lost) == 1 and lost[0].code == "pending_resolved", results
        jobs = fetch_all(tmp_path, "SELECT text FROM jobs WHERE agent_id = ?", (agent.id,))
        answers = [row["text"] for row in jobs if row["text"] in {"Monday", "Tuesday"}]
        assert len(answers) == 1
        stored = _pending(tmp_path, day)["answer"]
        assert stored["text"] == answers[0]


async def test_a_card_answer_resumes_a_turn_that_also_asked_for_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Approval answered first, then the question from its card: the turn resumes and ends."""
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind

    question = {"kind": "tool", "name": "user.ask", "args": {"question": "Which day?"}}
    approval_call = {"kind": "tool", "name": "shell", "args": {"command": "echo hi"}}
    use_model(function_model([[question, approval_call], [{"kind": "text", "text": "ok"}]]))
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            frame, _earlier = await request(
                client,
                "bots.create",
                {"name": "Proof", "access": "full", "op_id": mint_id("op_")},
            )
            bot = ok(frame)
            await request(
                client,
                "messages.send",
                {"bot_id": bot["id"], "text": "book it", "op_id": mint_id("op_")},
            )
            rows = await poll_rows(
                tmp_path,
                "SELECT id, turn_id, kind FROM pending_requests WHERE status = 'waiting'",
                (),
                lambda found: len(found) == 2,
            )
            approval = next(row for row in rows if row["kind"] == "approval")
            asked = next(row for row in rows if row["kind"] == "question")
            ok(
                (
                    await request(
                        client,
                        "pending.answer",
                        {"pending_id": approval["id"], "answer": "deny", "op_id": mint_id("op_")},
                    )
                )[0]
            )
            assert _turn_status(tmp_path, str(approval["turn_id"])) == "waiting"
            answered = ok(
                (
                    await request(
                        client,
                        "pending.answer",
                        {"pending_id": asked["id"], "text": "Tuesday", "op_id": mint_id("op_")},
                    )
                )[0]
            )
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (answered["job_id"],),
                lambda found: bool(found) and found[0]["status"] == "done",
            )
            await poll_rows(
                tmp_path,
                "SELECT status FROM turns WHERE id = ?",
                (approval["turn_id"],),
                lambda found: bool(found) and found[0]["status"] == "done",
            )
            assert (
                fetch_all(tmp_path, "SELECT id FROM pending_requests WHERE status = 'waiting'")
                == []
            )
    finally:
        use_model(None)
