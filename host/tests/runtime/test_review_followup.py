"""Regressions from the fourth PR9 review, through real host/runtime paths."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from sevn.domain.bots import BotService
from sevn.domain.errors import DomainError
from sevn.memory.store import MemoryStore
from sevn.runtime.models import use_model
from sevn.runtime.worker import bind
from support.botcore import arm_configured, upgrade_home
from support.chat import connected, fetch_all, load_modules, mint_id, ok, poll_rows, request


async def test_cancel_with_two_backlogs_respects_bot_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm_configured(monkeypatch, tmp_path)
    monkeypatch.setenv("SEVN_BOTS__MAX_PARALLEL_AGENTS", "1")
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof")
    release = asyncio.Event()
    started: asyncio.Queue[None] = asyncio.Queue()

    async def respond(_messages, _info):
        started.put_nowait(None)
        await release.wait()
        return ModelResponse(parts=[TextPart("ok")])

    use_model(FunctionModel(respond))
    load_modules("sevn.api.bots", "sevn.api.messages")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            worker = bind(host.hub)

            async def send(text, agent_id=None):
                params = {"bot_id": bot.id, "text": text, "op_id": mint_id("op_")}
                if agent_id:
                    params["agent_id"] = agent_id
                return ok((await request(client, "messages.send", params))[0])

            first = await send("first request")
            await asyncio.wait_for(started.get(), 5)
            turns = fetch_all(tmp_path, "SELECT id FROM turns WHERE status='running'")
            await send("follow-up", first["agent_id"])
            await send("/new second lane")
            ok(
                (
                    await request(
                        client, "turns.cancel", {"turn_id": turns[0]["id"], "op_id": mint_id("op_")}
                    )
                )[0]
            )
            await asyncio.wait_for(started.get(), 5)
            await worker.settle(first["agent_id"])
            await asyncio.sleep(0.1)
            assert len(fetch_all(tmp_path, "SELECT id FROM turns WHERE status='running'")) == 1
            assert started.empty()
            release.set()
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs",
                (),
                lambda rows: all(row["status"] in {"done", "cancelled"} for row in rows),
            )
    finally:
        release.set()
        use_model(None)


@pytest.mark.parametrize("restart", [False, True])
async def test_memory_deletion_survives_failed_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, restart: bool
) -> None:
    from sevn.memory import context

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof")
    store = MemoryStore()
    turn_id = mint_id("turn_")
    memory = await store.save(bot.id, "fixture preference", turn_id=turn_id, tier="pinned")
    await store.commit(turn_id)
    captured = []

    async def respond(messages, _info):
        captured.append(str(messages))
        if len(captured) == 2:
            raise RuntimeError("simulated provider failure")
        return ModelResponse(parts=[TextPart("ok")])

    use_model(FunctionModel(respond))
    load_modules("sevn.api.bots", "sevn.api.messages")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)

            async def send(text, agent_id=None, expected="done"):
                params = {"bot_id": bot.id, "text": text, "op_id": mint_id("op_")}
                if agent_id:
                    params["agent_id"] = agent_id
                sent = ok((await request(client, "messages.send", params))[0])
                await poll_rows(
                    tmp_path,
                    "SELECT status FROM jobs WHERE id=?",
                    (sent["job_id"],),
                    lambda rows: bool(rows) and rows[0]["status"] == expected,
                )
                return sent

            first = await send("first request")
            await store.delete(memory.id)
            await send("fails", first["agent_id"], "failed")
            if restart:
                context._shown.clear()
            await send("retry", first["agent_id"])
    finally:
        use_model(None)
    assert len(captured) == 3
    assert "removed, no longer holds: fixture preference" in captured[2]


async def test_staged_promotions_reserve_pinned_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof")
    store = MemoryStore()
    seed = mint_id("turn_")
    first = await store.save(bot.id, "a" * 3000, turn_id=seed)
    second = await store.save(bot.id, "b" * 3000, turn_id=seed)
    await store.commit(seed)
    turn_id = mint_id("turn_")
    await store.stage_tier(first.id, "pinned", actor="bot", revision=1, turn_id=turn_id)
    with pytest.raises(DomainError, match="pinned memory budget exceeded") as caught:
        await store.stage_tier(second.id, "pinned", actor="bot", revision=1, turn_id=turn_id)
    assert caught.value.code == "pinned_budget"
    await store.rollback(turn_id)


async def test_missing_route_target_continues_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.decisions.base import RouteDecision, attempt_for
    from sevn.decisions.llm import LLMDecider
    from sevn.decisions.registry import decide
    from sevn.domain.routing import RoutedMessage, RouterContext
    from sevn.store.db import utcnow

    arm_configured(monkeypatch, tmp_path)
    monkeypatch.setenv("SEVN_DECISIONS__PROVIDER", "llm")
    monkeypatch.setenv("SEVN_OLLAMA_URL", "")
    await upgrade_home(tmp_path)

    async def invalid(_self, _state):
        return attempt_for(RouteDecision("follow_up", "missing", 1.0, "llm"))

    monkeypatch.setattr(LLMDecider, "attempt", invalid)
    context = RouterContext(
        bot_id="bot_fixture",
        open_agents=[],
        pending_questions=[],
        recent_user_messages={},
        runtime="pydantic_ai",
    )
    message = RoutedMessage(
        text="hello",
        author="user",
        created_at=utcnow(),
        source="user",
        new_agent=False,
        reply_to=None,
        reply_to_agent_id=None,
        agent_id=None,
    )
    chosen = await decide(message, context, record=False)
    assert chosen.path == "default"
    assert chosen.intent == "new_request"


def test_routing_choices_keep_ids_and_separator_titles() -> None:
    from sevn.decisions.default import DefaultDecider
    from sevn.domain.routing import OpenAgent, RouterContext, _message_parts

    context = RouterContext(
        bot_id="bot_fixture",
        open_agents=[
            OpenAgent(id=key, title="A|B", summary="", status="idle")
            for key in ("agent_first", "agent_second")
        ],
        pending_questions=[],
        recent_user_messages={},
        runtime="pydantic_ai",
    )
    parts = _message_parts("hello", DefaultDecider().decide(context), "")
    choices = json.loads(parts[1]["choices"])
    assert choices == [
        {"label": "New task", "agent_id": None},
        {"label": "Continue: A|B", "agent_id": "agent_first"},
        {"label": "Continue: A|B", "agent_id": "agent_second"},
    ]


@pytest.mark.parametrize("approval_first,sequential", [(False, False), (True, False), (True, True)])
async def test_question_and_approval_complete_in_either_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, approval_first: bool, sequential: bool
) -> None:
    from fakes.models import function_model

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof", access="full")
    question = {"kind": "tool", "name": "user.ask", "args": {"question": "Which day?"}}
    approval_call = {"kind": "tool", "name": "shell", "args": {"command": "echo hi"}}
    stages = [[approval_call], [question]] if sequential else [[question, approval_call]]
    stages.append([{"kind": "text", "text": "ok"}])
    use_model(function_model(stages))
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            await request(
                client,
                "messages.send",
                {"bot_id": bot.id, "text": "book it", "op_id": mint_id("op_")},
            )
            rows = await poll_rows(
                tmp_path,
                "SELECT id,turn_id,kind FROM pending_requests WHERE status='waiting'",
                (),
                lambda rows: len(rows) == (1 if sequential else 2),
            )
            approval = next(row for row in rows if row["kind"] == "approval")

            async def answer_approval():
                ok(
                    (
                        await request(
                            client,
                            "pending.answer",
                            {
                                "pending_id": approval["id"],
                                "answer": "deny",
                                "op_id": mint_id("op_"),
                            },
                        )
                    )[0]
                )

            if approval_first:
                await answer_approval()
            if sequential:
                await poll_rows(
                    tmp_path,
                    "SELECT id FROM pending_requests WHERE kind='question' AND status='waiting'",
                    (),
                    bool,
                )
            answer = ok(
                (
                    await request(
                        client,
                        "messages.send",
                        {"bot_id": bot.id, "text": "Tuesday", "op_id": mint_id("op_")},
                    )
                )[0]
            )
            if not approval_first:
                original = fetch_all(
                    tmp_path, "SELECT status FROM turns WHERE id=?", (approval["turn_id"],)
                )
                assert original[0]["status"] == "waiting"
                await answer_approval()
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id=?",
                (answer["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
            )
            assert (
                fetch_all(tmp_path, "SELECT id FROM pending_requests WHERE status='waiting'") == []
            )
            assert (
                fetch_all(tmp_path, "SELECT status FROM turns WHERE id=?", (approval["turn_id"],))[
                    0
                ]["status"]
                == "done"
            )
    finally:
        use_model(None)


async def test_uncorrelated_correction_does_not_change_another_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.decisions.base import RouteDecision, attempt_for
    from sevn.decisions.log import mark_corrected, record_attempt

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    await record_attempt("fixture", attempt_for(RouteDecision("new_request", None, 1.0, "rule")))
    await mark_corrected(None, "agent_other")
    assert fetch_all(tmp_path, "SELECT corrected_to FROM decision_log")[0]["corrected_to"] is None
