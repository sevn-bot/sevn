"""Phase 6: the 60-second daily brief."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from support.chat import connected, load_modules, mint_id, ok, request


async def _bot(client: Any, name: str) -> str:
    frame, _earlier = await request(client, "bots.create", {"name": name, "op_id": mint_id("op_")})
    bot_id = ok(frame)["id"]
    assert isinstance(bot_id, str)
    return bot_id


async def _turn(
    agent_id: str, status: str, finished: datetime, reply: str, cost: float | None = None
) -> None:
    from sevn.domain.session import open_session
    from sevn.store.models import Agent, Message, Turn

    async with open_session() as session:
        agent = await session.get(Agent, agent_id)
        assert agent is not None
        turn_id = mint_id("turn_")
        usage: dict[str, object] = {}
        if cost is not None:
            usage = {"input_tokens": 10, "cost_usd": cost, "cost_source": "price_table"}
        session.add(
            Turn(
                id=turn_id,
                agent_id=agent_id,
                thread_id=agent.thread_id,
                job_ids=[],
                status=status,
                model="m",
                usage=usage,
                model_messages=None,
                started_at=finished - timedelta(seconds=5),
                finished_at=finished,
            )
        )
        await session.flush()
        session.add(
            Message(
                id=mint_id("msg_"),
                thread_id=agent.thread_id,
                turn_id=turn_id,
                agent_id=agent_id,
                role="assistant",
                author=agent.bot_id,
                parts=[{"type": "text", "text": reply}],
                created_at=finished,
            )
        )
        await session.commit()


async def _question(agent_id: str, text: str, *, due: datetime | None, age: timedelta) -> None:
    from sevn.domain.session import open_session
    from sevn.store.models import Agent, PendingRequest, Turn

    async with open_session() as session:
        agent = await session.get(Agent, agent_id)
        assert agent is not None
        turn_id = mint_id("turn_")
        now = datetime.now(UTC)
        session.add(
            Turn(
                id=turn_id,
                agent_id=agent_id,
                thread_id=agent.thread_id,
                job_ids=[],
                status="waiting",
                model="m",
                usage={},
                model_messages=None,
                started_at=now - age,
                finished_at=None,
            )
        )
        await session.flush()
        session.add(
            PendingRequest(
                id=mint_id("pend_"),
                turn_id=turn_id,
                agent_id=agent_id,
                kind="question",
                tool_call_id=None,
                payload={
                    "text": text,
                    "priority": "high",
                    "due_by": None if due is None else due.isoformat(),
                    "blocking": True,
                    "options": [],
                },
                answer=None,
                status="waiting",
                created_at=now - age,
                resolved_at=None,
            )
        )
        await session.commit()


async def test_brief_covers_decisions_finished_routines_and_trouble(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.domain.metrics import report
    from sevn.domain.routines import RoutineService

    load_modules("sevn.api.bots", "sevn.api.fleet")
    now = datetime.now(UTC)
    async with connected(tmp_path, monkeypatch) as (_host, client):
        from sevn.domain.host_status import reset_cache

        # connected() clears SEVN_OLLAMA_URL; point it at a closed port here.
        monkeypatch.setenv("SEVN_OLLAMA_URL", "http://127.0.0.1:9")
        reset_cache()
        atlas = await _bot(client, "Atlas")
        nimbus = await _bot(client, "Nimbus")
        lane = await AgentService().spawn(atlas, title="Scan")
        other = await AgentService().spawn(nimbus, title="Draft")
        await _turn(lane.id, "done", now - timedelta(hours=2), "3 prices changed", cost=0.4)
        await _turn(lane.id, "done", now - timedelta(hours=9), "No changes today")
        await _turn(other.id, "failed", now - timedelta(hours=1), "This turn failed.")
        await _turn(lane.id, "done", now - timedelta(hours=30), "Old news")
        for index in range(4):
            await _question(
                other.id,
                f"Question {index}",
                due=now - timedelta(hours=1) if index == 0 else None,
                age=timedelta(hours=index + 1),
            )
        daily = await RoutineService().create(
            atlas, name="Price scan", schedule="0 */6 * * *", timezone="UTC", text="Scan."
        )
        weekly = await RoutineService().create(
            atlas, name="Weekly", schedule="0 0 1 1 *", timezone="UTC", text="Once a year."
        )
        starved = await RoutineService().create(
            nimbus, name="Starved", schedule="0 * * * *", timezone="UTC", text="Hourly."
        )
        await RoutineService().pause(starved.id, reason="budget")
        await report(atlas, key="subscribers", value=3200, source="api")
        await report(
            atlas,
            key="visits",
            value=900,
            source="Plausible",
            as_of=(now - timedelta(hours=5)).isoformat(),
            freshness_minutes=60,
        )
        frame, _earlier = await request(client, "fleet.brief", {})
        brief = ok(frame)
    assert abs((datetime.fromisoformat(brief["built_at"]) - now).total_seconds()) < 60
    assert brief["decisions_total"] == 4
    assert len(brief["decisions"]) == 3
    assert brief["finished_done"] == 2
    assert brief["finished_failed"] == 1
    assert [item["preview"] for item in brief["finished_top"]] == [
        "3 prices changed",
        "No changes today",
    ]
    names = [item["name"] for item in brief["routines_today"]]
    assert names == ["Price scan"]
    assert daily.id == brief["routines_today"][0]["id"]
    assert brief["routines_today"][0]["runs"] == 4
    assert weekly.id not in {item["id"] for item in brief["routines_today"]}
    assert {tile["key"] for tile in brief["kpis"]} >= {"spend_today", "waiting"}
    kinds = {issue["kind"] for issue in brief["broken"]}
    assert kinds == {
        "failed_turns",
        "overdue_question",
        "paused_by_budget",
        "stale_metric",
        "ollama_down",
    }
    texts = " ".join(issue["text"] for issue in brief["broken"])
    assert "Nimbus" in texts
    assert "Starved" in texts
    assert "visits" in texts
    assert "1 overdue" in texts
    assert {tile["key"] for tile in brief["metric_changes"]} == {"visits"}


async def test_a_quiet_night_has_nothing_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_modules("sevn.api.bots", "sevn.api.fleet")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        await _bot(client, "Atlas")
        frame, _earlier = await request(client, "fleet.brief", {})
        brief = ok(frame)
    assert brief["broken"] == []
    assert brief["decisions"] == []
    assert brief["finished_done"] == 0
    assert brief["routines_today"] == []
    assert brief["routines_today_usd"] == 0


async def test_the_brief_sees_past_the_dashboard_caps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale metric older than the 8 newest, and done turns behind 20 newer failures."""
    from sevn.domain.agents import AgentService
    from sevn.domain.metrics import report

    load_modules("sevn.api.bots", "sevn.api.fleet")
    now = datetime.now(UTC)
    async with connected(tmp_path, monkeypatch) as (_host, client):
        atlas = await _bot(client, "Atlas")
        lane = await AgentService().spawn(atlas, title="Scan")
        await _turn(lane.id, "done", now - timedelta(hours=3), "the useful one")
        for index in range(21):
            await _turn(lane.id, "failed", now - timedelta(minutes=60 - index), "This turn failed.")
        await report(
            atlas,
            key="old-visits",
            value=900,
            source="Plausible",
            as_of=(now - timedelta(hours=5)).isoformat(),
            freshness_minutes=60,
        )
        for index in range(9):
            await report(atlas, key=f"fresh-{index}", value=index, source="api")
        frame, _earlier = await request(client, "fleet.brief", {})
        brief = ok(frame)
    assert [item["preview"] for item in brief["finished_top"]] == ["the useful one"]
    texts = " ".join(issue["text"] for issue in brief["broken"])
    assert "old-visits is stale" in texts
