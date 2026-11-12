"""Router spend: each routing step records what its model call used (fleet plan)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fakes.fake_jev import FAKE_JEV_USAGE, FakeJev
from fakes.fake_ollama import FAKE_OLLAMA_TOKENS, FakeOllama
from fakes.models import function_model
from support.botcore import (
    arm_configured,
    decision_text,
    secrets_toml,
    set_provider_key,
    upgrade_home,
)
from support.chat import connected, fetch_all, load_modules, mint_id, ok, request

_BOT = "bot_router"
# Skip jev so the LLM, Ollama and CLI steps run.
_LLM_FIRST = secrets_toml('[decisions]\nprovider = "llm"\n')


def _message(text: str) -> object:
    from sevn.domain.routing import RoutedMessage

    return RoutedMessage(
        text=text,
        author="user",
        created_at=datetime.now(UTC),
        source="user",
        new_agent=False,
        reply_to=None,
        reply_to_agent_id=None,
        agent_id=None,
    )


def _context(*, runtime: str = "pydantic_ai") -> object:
    from sevn.domain.routing import OpenAgent, RouterContext

    return RouterContext(
        bot_id=_BOT,
        open_agents=[OpenAgent(id="agent_a", title="Invoice", summary="taxes", status="idle")],
        pending_questions=[],
        recent_user_messages={},
        runtime=runtime,
    )


def _rows(home: Path) -> list[dict[str, Any]]:
    rows = fetch_all(home, "SELECT path, bot_id, usage FROM decision_log ORDER BY created_at")
    return [
        {
            "path": row["path"],
            "bot_id": row["bot_id"],
            "usage": None if row["usage"] is None else json.loads(row["usage"]),
        }
        for row in rows
    ]


class _Shot:
    """A CLI one-shot that reports a subscription turn's usage."""

    def __init__(self, text: str) -> None:
        self.text = text

    async def open(self, agent: object) -> object:
        from sevn.runtime.base import SessionRef

        return SessionRef(agent_id=str(getattr(agent, "id", "x")), session_ref="shot")

    def run_turn(self, turn: object) -> AsyncIterator[object]:
        from sevn.runtime.events import RuntimeEvent
        from sevn.runtime.usage import usage_record

        _ = turn
        text = self.text

        async def generate() -> AsyncIterator[object]:
            yield RuntimeEvent(
                kind="turn_finished",
                text=text,
                model_messages=[],
                usage=usage_record(
                    {"requests": 1, "input_tokens": 300, "output_tokens": 20},
                    cost_usd=None,
                    cost_source="subscription",
                    estimated_usd=0.004,
                ),
            )

        return generate()

    async def close(self, agent_id: str) -> None:
        _ = agent_id


def _reset() -> None:
    from sevn.decisions.cli_oneshot import use_runtime
    from sevn.decisions.jev import use_client
    from sevn.runtime.models import use_model

    use_client(None)
    use_runtime(None)
    use_model(None)


async def test_jev_step_records_its_tokens_and_an_unknown_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.decisions.jev import use_client
    from sevn.decisions.registry import decide

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    use_client(
        FakeJev(
            answers={
                "message.intent": ("new_request", 0.99),
                "message.target_agent": ("none", 0.99),
            }
        )
    )
    try:
        decision = await decide(_message("plan a trip"), _context())
    finally:
        _reset()
    assert decision.path == "jev"
    [row] = _rows(tmp_path)
    assert row["bot_id"] == _BOT
    usage = row["usage"]
    assert usage["requests"] == 1
    assert (usage["input_tokens"], usage["output_tokens"]) == FAKE_JEV_USAGE
    # jev reports tokens but no price.
    assert usage["cost_source"] == "unknown"
    assert usage["cost_usd"] is None


async def test_llm_ollama_and_cli_steps_record_their_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A low LLM answer falls to Ollama: both rows carry usage, Ollama's is local."""
    from sevn.decisions.registry import decide
    from sevn.runtime.models import use_model

    arm_configured(monkeypatch, tmp_path, _LLM_FIRST)
    await upgrade_home(tmp_path)
    set_provider_key()
    use_model(
        function_model([{"kind": "text", "text": decision_text("follow_up", "agent_a", 0.3)}])
    )
    try:
        with FakeOllama(decision_text("follow_up", "agent_a", 0.95)) as ollama:
            monkeypatch.setenv("SEVN_OLLAMA_URL", ollama.url)
            decision = await decide(_message("follow up on the invoice"), _context())
    finally:
        _reset()
    assert decision.path == "ollama"
    llm, local = _rows(tmp_path)
    assert llm["path"] == "llm"
    assert llm["usage"]["requests"] == 1
    assert llm["usage"]["input_tokens"] > 0
    # The test model has no price; a real provider model is priced per response.
    assert llm["usage"]["cost_source"] == "unknown"
    assert local["path"] == "ollama"
    assert (local["usage"]["input_tokens"], local["usage"]["output_tokens"]) == FAKE_OLLAMA_TOKENS
    assert local["usage"]["cost_source"] == "local"
    assert local["usage"]["cost_usd"] == 0


async def test_cli_step_records_a_subscription_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.decisions.cli_oneshot import use_runtime
    from sevn.decisions.registry import decide

    arm_configured(monkeypatch, tmp_path, _LLM_FIRST)
    await upgrade_home(tmp_path)
    use_runtime(_Shot(decision_text("new_request", None, 0.95)))
    try:
        decision = await decide(_message("plan a trip"), _context(runtime="claude"))
    finally:
        _reset()
    assert decision.path == "cli"
    [row] = _rows(tmp_path)
    assert row["usage"]["cost_source"] == "subscription"
    assert row["usage"]["input_tokens"] == 300
    assert row["usage"]["estimated_usd"] == pytest.approx(0.004)


async def test_rule_and_default_steps_record_no_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.decisions.registry import decide

    arm_configured(monkeypatch, tmp_path, _LLM_FIRST)
    await upgrade_home(tmp_path)
    try:
        ruled = await decide(_message("/new plan a trip"), _context())
        fallback = await decide(_message("hello there"), _context())
    finally:
        _reset()
    assert ruled.path == "rule"
    assert fallback.path == "default"
    # SQL NULL, not the JSON text "null", so the spend query can skip them in SQL.
    rows = fetch_all(
        tmp_path, "SELECT path, usage IS NULL AS missing FROM decision_log ORDER BY created_at"
    )
    assert [(row["path"], row["missing"]) for row in rows] == [("rule", 1), ("default", 1)]


async def _routing_row(bot_id: str, when: datetime, usage: dict[str, object]) -> None:
    from sevn.domain.session import open_session
    from sevn.store.models import DecisionLog

    async with open_session() as session:
        session.add(
            DecisionLog(
                id=mint_id("dec_"),
                point="route",
                input_hash="x",
                state_redacted="",
                answers={},
                confidences={},
                path="llm",
                outcome="new_request",
                corrected_to=None,
                created_at=when,
                bot_id=bot_id,
                usage=usage,
            )
        )
        await session.commit()


def _priced(cost: float, tokens: int = 1000) -> dict[str, object]:
    from sevn.runtime.usage import usage_record

    return usage_record(
        {"requests": 1, "input_tokens": tokens, "output_tokens": 0},
        cost_usd=cost,
        cost_source="price_table",
    )


@pytest.mark.parametrize("minute", [0, 2, 720])
async def test_routing_spend_joins_the_spend_tokens_and_cost_grid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minute: int
) -> None:
    from sevn.domain import fleet
    from sevn.runtime.usage import usage_record

    now = datetime(2026, 11, 12, tzinfo=UTC) + timedelta(minutes=minute)
    monkeypatch.setattr(fleet, "utcnow", lambda: now)
    load_modules("sevn.api.bots", "sevn.api.fleet")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        frame, _earlier = await request(
            client, "bots.create", {"name": "Router", "op_id": mint_id("op_")}
        )
        bot_id = ok(frame)["id"]
        await _routing_row(bot_id, now, _priced(0.25, tokens=1000))
        await _routing_row(
            bot_id,
            now,
            usage_record(
                {"requests": 1, "input_tokens": 120, "output_tokens": 8},
                cost_usd=None,
                cost_source="unknown",
            ),
        )
        # Yesterday's routing does not count today.
        await _routing_row(bot_id, now - timedelta(days=1), _priced(9.0))
        frame, _earlier = await request(client, "fleet.overview", {})
        body = ok(frame)
    kpis = {tile["key"]: tile for tile in body["kpis"]}
    spend = kpis["spend_today"]
    assert spend["value"] == pytest.approx(0.25)
    assert spend["unpriced"] == 1
    assert "routing calls not included" not in spend["note"]
    assert "2 routing calls" in spend["note"]
    assert kpis["tokens_today"]["value"] == 1000 + 128
    today = now.date().isoformat()
    cell = next(row for row in body["activity"] if row["bot_id"] == bot_id and row["day"] == today)
    assert cell["cost_usd"] == pytest.approx(0.25)
    # Routing calls are spend, not finished turns.
    assert cell["turns"] == 0


@pytest.mark.parametrize("minute", [0, 2, 720])
async def test_routing_spend_counts_toward_a_bot_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minute: int
) -> None:
    from sevn.domain.session import open_session
    from sevn.domain.spend import day_start, spend_by_bot

    load_modules("sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        frame, _earlier = await request(
            client, "bots.create", {"name": "Router", "op_id": mint_id("op_")}
        )
        bot_id = ok(frame)["id"]
        now = datetime(2026, 11, 12, tzinfo=UTC) + timedelta(minutes=minute)
        await _routing_row(bot_id, now, _priced(0.4))
        async with open_session() as session:
            spent = await spend_by_bot(session, day_start(now))
    assert spent == {bot_id: pytest.approx(0.4)}
