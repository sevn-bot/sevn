"""Phase 4: routines, the scheduler, silent runs, budgets and the Upcoming panel."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fakes.models import function_model
from support.chat import connected, fetch_all, load_modules, mint_id, ok, poll_rows, request

_MODULES = ("sevn.api.bots", "sevn.api.messages", "sevn.api.routines", "sevn.api.fleet")


async def _bot(client: Any, name: str = "Nimbus") -> str:
    frame, _earlier = await request(client, "bots.create", {"name": name, "op_id": mint_id("op_")})
    bot_id = ok(frame)["id"]
    assert isinstance(bot_id, str)
    return bot_id


_READ_ONLY = frozenset({"routines.list", "fleet.overview"})


async def _call(client: Any, method: str, **params: object) -> dict[str, Any]:
    """Mutating methods need an ``op_id``; read-only ones refuse one."""
    body = dict(params) if method in _READ_ONLY else {**params, "op_id": mint_id("op_")}
    frame, _earlier = await request(client, method, body)
    return frame


async def _create(client: Any, bot_id: str, **extra: object) -> dict[str, Any]:
    params: dict[str, object] = {
        "bot_id": bot_id,
        "name": "Mentions scan",
        "schedule": "0 */2 * * *",
        "timezone": "UTC",
        "text": "Scan new mentions and report anything that needs a reply.",
        **extra,
    }
    return ok(await _call(client, "routines.create", **params))


def _events(home: Path, kind: str) -> list[str]:
    return [
        row["payload"]
        for row in fetch_all(home, "SELECT payload FROM events WHERE type = ?", (kind,))
    ]


async def test_create_list_and_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    load_modules(*_MODULES)
    async with connected(tmp_path, monkeypatch) as (_host, client):
        bot_id = await _bot(client)
        before = datetime.now(UTC)
        created = await _create(client, bot_id, timezone="Europe/Amsterdam")
        assert created["id"].startswith("rtn_")
        assert created["status"] == "active"
        assert created["paused_reason"] is None
        next_run = datetime.fromisoformat(created["next_run"])
        assert before < next_run <= before + timedelta(hours=2, minutes=1)
        assert next_run.minute == 0
        listed = ok(await _call(client, "routines.list", bot_id=bot_id))["routines"]
        assert [item["id"] for item in listed] == [created["id"]]
        paused = ok(await _call(client, "routines.pause", routine_id=created["id"]))
        assert paused["status"] == "paused"
        assert paused["paused_reason"] == "user"
        resumed = ok(await _call(client, "routines.resume", routine_id=created["id"]))
        assert resumed["status"] == "active"
        assert resumed["paused_reason"] is None
        updated = ok(
            await _call(client, "routines.update", routine_id=created["id"], schedule="0 9 * * 1")
        )
        assert updated["schedule"] == "0 9 * * 1"
        assert datetime.fromisoformat(updated["next_run"]).astimezone(UTC).hour in {7, 8}
        cancelled = ok(await _call(client, "routines.cancel", routine_id=created["id"]))
        assert cancelled["status"] == "cancelled"
        assert cancelled["next_run"] is None
        assert ok(await _call(client, "routines.list", bot_id=bot_id))["routines"] == []
        everything = ok(
            await _call(client, "routines.list", bot_id=bot_id, include_cancelled=True)
        )["routines"]
        assert [item["status"] for item in everything] == ["cancelled"]
        frame = await _call(client, "routines.resume", routine_id=created["id"])
        assert frame["e"]["code"] == "invalid_params"
    assert len(_events(tmp_path, "routine.updated")) >= 5


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schedule", "every day"),
        ("schedule", "0 0 30 2 *"),
        ("timezone", "Mars/Olympus"),
        ("name", "  "),
        ("text", ""),
    ],
)
async def test_bad_routines_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    load_modules(*_MODULES)
    async with connected(tmp_path, monkeypatch) as (_host, client):
        bot_id = await _bot(client)
        params: dict[str, object] = {
            "bot_id": bot_id,
            "name": "Scan",
            "schedule": "0 * * * *",
            "timezone": "UTC",
            "text": "Scan.",
            field: value,
        }
        frame = await _call(client, "routines.create", **params)
        assert frame["e"]["code"] == "invalid_params", frame
        unknown = await _call(
            client,
            "routines.create",
            bot_id="bot_missing",
            name="Scan",
            schedule="0 * * * *",
            timezone="UTC",
            text="Scan.",
        )
        assert unknown["e"]["code"] == "not_found"


async def _make_due(home: Path, routine_id: str, when: datetime) -> None:
    from sevn.domain.session import open_session
    from sevn.store.models import Routine

    async with open_session() as session:
        row = await session.get(Routine, routine_id)
        assert row is not None
        row.next_run = when
        await session.commit()


async def test_scheduler_runs_a_due_routine_once_on_a_new_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.routines import run_due

    load_modules(*_MODULES)
    async with connected(tmp_path, monkeypatch) as (host, client):
        bot_id = await _bot(client)
        routine = await _create(client, bot_id)
        other = await _create(client, bot_id, name="Later", schedule="0 0 1 1 *")
        now = datetime.now(UTC)
        # Missed for three days: one catch-up run, not one per slot.
        await _make_due(tmp_path, routine["id"], now - timedelta(days=3))
        jobs = await run_due(host.hub, now=now)
        assert len(jobs) == 1
        rows = fetch_all(
            tmp_path,
            "SELECT id, origin, routine_id, agent_id, text, status FROM jobs WHERE id = ?",
            (jobs[0],),
        )
        assert rows[0]["origin"] == "routine"
        assert rows[0]["routine_id"] == routine["id"]
        assert rows[0]["text"].startswith("Scan new mentions")
        agent = fetch_all(tmp_path, "SELECT title FROM agents WHERE id = ?", (rows[0]["agent_id"],))
        assert agent[0]["title"] == "Mentions scan"
        stored = fetch_all(
            tmp_path, "SELECT last_run, next_run FROM routines WHERE id = ?", (routine["id"],)
        )
        assert datetime.fromisoformat(stored[0]["last_run"]) == now
        assert datetime.fromisoformat(stored[0]["next_run"]) > now
        assert await run_due(host.hub, now=now) == []
        untouched = fetch_all(
            tmp_path, "SELECT last_run FROM routines WHERE id = ?", (other["id"],)
        )
        assert untouched[0]["last_run"] is None
    runs = _events(tmp_path, "routine.run")
    assert len(runs) == 1 and routine["id"] in runs[0]


async def test_a_retried_occurrence_queues_one_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sweep that stops after the job but before the cursor moves runs the slot once."""
    from sevn.domain.routines import run_due

    load_modules(*_MODULES)
    async with connected(tmp_path, monkeypatch) as (host, client):
        bot_id = await _bot(client)
        routine = await _create(client, bot_id)
        now = datetime.now(UTC)
        slot = now - timedelta(minutes=5)
        await _make_due(tmp_path, routine["id"], slot)
        first = await run_due(host.hub, now=now)
        assert len(first) == 1
        # The host stopped before the cursor update: the slot is due again.
        await _make_due(tmp_path, routine["id"], slot)
        assert await run_due(host.hub, now=now + timedelta(seconds=30)) == []
        jobs = fetch_all(tmp_path, "SELECT id FROM jobs WHERE routine_id = ?", (routine["id"],))
        assert [row["id"] for row in jobs] == first
        stored = fetch_all(tmp_path, "SELECT next_run FROM routines WHERE id = ?", (routine["id"],))
        assert datetime.fromisoformat(stored[0]["next_run"]) > now


async def test_a_stop_while_announcing_the_run_does_not_run_it_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from sevn.domain.routines import run_due

    load_modules(*_MODULES)
    async with connected(tmp_path, monkeypatch) as (host, client):
        bot_id = await _bot(client)
        routine = await _create(client, bot_id)
        now = datetime.now(UTC)
        await _make_due(tmp_path, routine["id"], now - timedelta(minutes=5))
        emit = host.hub.emit

        async def stopping(kind: str, *args: object, **kwargs: object) -> object:
            if kind == "routine.run":
                raise asyncio.CancelledError
            return await emit(kind, *args, **kwargs)

        monkeypatch.setattr(host.hub, "emit", stopping)
        with pytest.raises(asyncio.CancelledError):
            await run_due(host.hub, now=now)
        monkeypatch.setattr(host.hub, "emit", emit)
        await run_due(host.hub, now=now + timedelta(seconds=30))
        jobs = fetch_all(tmp_path, "SELECT id FROM jobs WHERE routine_id = ?", (routine["id"],))
        assert len(jobs) == 1


async def test_paused_cancelled_and_paused_bot_do_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.routines import run_due

    load_modules(*_MODULES)
    async with connected(tmp_path, monkeypatch) as (host, client):
        bot_id = await _bot(client)
        paused = await _create(client, bot_id, name="Paused")
        cancelled = await _create(client, bot_id, name="Cancelled")
        ok(await _call(client, "routines.pause", routine_id=paused["id"]))
        ok(await _call(client, "routines.cancel", routine_id=cancelled["id"]))
        sleepy = await _bot(client, "Sleepy")
        on_paused_bot = await _create(client, sleepy, name="On a paused bot")
        ok(await _call(client, "bots.update", bot_id=sleepy, paused=True))
        now = datetime.now(UTC)
        for routine_id in (paused["id"], on_paused_bot["id"]):
            await _make_due(tmp_path, routine_id, now - timedelta(minutes=5))
        assert await run_due(host.hub, now=now) == []
        skipped = fetch_all(
            tmp_path, "SELECT next_run, last_run FROM routines WHERE id = ?", (on_paused_bot["id"],)
        )
        assert datetime.fromisoformat(skipped[0]["next_run"]) > now
        assert skipped[0]["last_run"] is None
    assert fetch_all(tmp_path, "SELECT id FROM jobs") == []


async def _spent_today(home: Path, bot_id: str, cost: float) -> None:
    from sevn.domain.agents import AgentService
    from sevn.domain.session import open_session
    from sevn.store.models import Turn

    agent = await AgentService().spawn(bot_id)
    now = datetime.now(UTC)
    async with open_session() as session:
        session.add(
            Turn(
                id=mint_id("turn_"),
                agent_id=agent.id,
                thread_id=agent.thread_id,
                job_ids=[],
                status="done",
                model="test",
                usage={"input_tokens": 10, "cost_usd": cost, "cost_source": "price_table"},
                model_messages=None,
                started_at=now - timedelta(seconds=5),
                finished_at=now,
            )
        )
        await session.commit()


async def test_over_budget_pauses_routines_instead_of_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.routines import run_due

    load_modules(*_MODULES)
    monkeypatch.setenv("SEVN_BUDGETS__DAILY_USD_PER_BOT", "1.0")
    async with connected(tmp_path, monkeypatch) as (host, client):
        spender = await _bot(client, "Spender")
        frugal = await _bot(client, "Frugal")
        over = await _create(client, spender, name="Over")
        fine = await _create(client, frugal, name="Fine")
        await _spent_today(tmp_path, spender, 1.25)
        await _spent_today(tmp_path, frugal, 0.5)
        now = datetime.now(UTC)
        for routine_id in (over["id"], fine["id"]):
            await _make_due(tmp_path, routine_id, now - timedelta(minutes=1))
        jobs = await run_due(host.hub, now=now)
        assert len(jobs) == 1
        rows = fetch_all(
            tmp_path, "SELECT status, paused_reason FROM routines WHERE id = ?", (over["id"],)
        )
        assert rows[0]["status"] == "paused"
        assert rows[0]["paused_reason"] == "budget"
        ran = fetch_all(tmp_path, "SELECT routine_id FROM jobs WHERE id = ?", (jobs[0],))
        assert ran[0]["routine_id"] == fine["id"]


async def test_host_budget_pauses_every_routine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.routines import run_due

    load_modules(*_MODULES)
    monkeypatch.setenv("SEVN_BUDGETS__DAILY_USD_HOST", "2.0")
    async with connected(tmp_path, monkeypatch) as (host, client):
        first = await _bot(client, "First")
        second = await _bot(client, "Second")
        one = await _create(client, first, name="One")
        two = await _create(client, second, name="Two")
        await _spent_today(tmp_path, first, 1.5)
        await _spent_today(tmp_path, second, 0.75)
        now = datetime.now(UTC)
        for routine_id in (one["id"], two["id"]):
            await _make_due(tmp_path, routine_id, now - timedelta(minutes=1))
        assert await run_due(host.hub, now=now) == []
        rows = fetch_all(tmp_path, "SELECT paused_reason FROM routines ORDER BY name")
        assert [row["paused_reason"] for row in rows] == ["budget", "budget"]


def _clear() -> None:
    from sevn.decisions.jev import use_client
    from sevn.runtime.models import use_model

    use_client(None)
    use_model(None)


async def test_a_run_can_say_it_was_silent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fakes.fake_jev import FakeJev
    from sevn.decisions.jev import use_client
    from sevn.domain.routines import run_due
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind

    load_modules(*_MODULES)
    use_client(FakeJev(answers={}))
    use_model(
        function_model(
            [
                [{"kind": "tool", "name": "routine.silent", "args": {}}],
                [{"kind": "text", "text": "nothing new"}],
                [{"kind": "text", "text": "two replies need a look"}],
            ]
        )
    )
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot_id = await _bot(client)
            routine = await _create(client, bot_id)
            now = datetime.now(UTC)
            await _make_due(tmp_path, routine["id"], now - timedelta(minutes=1))
            quiet = (await run_due(host.hub, now=now))[0]
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (quiet,),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
            )
            later = now + timedelta(hours=2)
            await _make_due(tmp_path, routine["id"], later - timedelta(minutes=1))
            useful = (await run_due(host.hub, now=later))[0]
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (useful,),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
            )
            rows = {
                row["id"]: row["silent"]
                for row in fetch_all(tmp_path, "SELECT id, silent FROM jobs")
            }
            assert rows == {quiet: 1, useful: 0}
            overview = ok(await _call(client, "fleet.overview"))
            upcoming = {item["id"]: item for item in overview["upcoming"]}
            item = upcoming[routine["id"]]
            assert item["last_outcome"] == "ok"
            assert item["runs_30d"] == 2
            assert item["last_useful_at"] is not None
    finally:
        _clear()


async def test_a_claude_run_says_silent_with_its_reply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claude bots have no routine.silent tool; a reply starting with [silent] counts."""
    from fakes.fake_claude import FakeClaudeClient
    from sevn.domain.routines import run_due
    from sevn.runtime.runtimes.claude import use_client
    from sevn.runtime.worker import bind

    load_modules(*_MODULES)
    use_client(
        FakeClaudeClient(
            script=[{"type": "result", "subtype": "success", "result": "[silent] nothing new"}]
        )
    )
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            worker = bind(host.hub)
            try:
                frame, _earlier = await request(
                    client,
                    "bots.create",
                    {
                        "name": "Claude",
                        "runtime": "claude",
                        "access": "full",
                        "op_id": mint_id("op_"),
                    },
                )
                bot_id = ok(frame)["id"]
                # Bot core runs Claude only with full access and network on.
                ok(await _call(client, "bots.update", bot_id=bot_id, network="on"))
                routine = await _create(client, bot_id)
                now = datetime.now(UTC)
                await _make_due(tmp_path, routine["id"], now - timedelta(minutes=1))
                job_id = (await run_due(host.hub, now=now))[0]
                await poll_rows(
                    tmp_path,
                    "SELECT status FROM jobs WHERE id = ?",
                    (job_id,),
                    lambda rows: bool(rows) and rows[0]["status"] == "done",
                )
                rows = fetch_all(tmp_path, "SELECT text, silent FROM jobs WHERE id = ?", (job_id,))
                assert "routine.silent" not in rows[0]["text"]
                assert "[silent]" in rows[0]["text"]
                assert rows[0]["silent"] == 1
            finally:
                await worker.aclose()
    finally:
        use_client(None)


def test_only_a_leading_marker_is_silent() -> None:
    from sevn.tools.routine import is_silent_reply

    assert is_silent_reply("[silent] nothing new")
    assert is_silent_reply("  [SILENT]")
    assert not is_silent_reply("Found two. Not [silent].")
    assert not is_silent_reply("")


async def test_silent_outside_a_routine_run_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.tools.registry import TurnDeps
    from sevn.tools.routine import routine_toolset

    load_modules(*_MODULES)
    async with connected(tmp_path, monkeypatch) as (_host, _client):
        tools = routine_toolset(TurnDeps(bot_id="bot_x", agent_id="agent_x", turn_id="turn_x"))
        assert isinstance(tools, dict)
        assert await tools["routine.silent"]() == "not a routine run"


async def _routine_turn(
    home: Path,
    routine_id: str,
    bot_id: str,
    finished: datetime,
    *,
    cost: float | None,
    silent: bool = False,
    source: str = "price_table",
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.domain.session import open_session
    from sevn.store.models import Job, Turn

    agent = await AgentService().spawn(bot_id)
    job_id = mint_id("job_")
    async with open_session() as session:
        session.add(
            Job(
                id=job_id,
                to_bot_id=bot_id,
                agent_id=agent.id,
                route_decision_id=None,
                origin="routine",
                text="scan",
                attachments=[],
                reply_to=None,
                expects_reply=True,
                hop=0,
                status="done",
                created_at=finished - timedelta(seconds=10),
                started_at=finished - timedelta(seconds=9),
                finished_at=finished,
                routine_id=routine_id,
                silent=silent,
            )
        )
        session.add(
            Turn(
                id=mint_id("turn_"),
                agent_id=agent.id,
                thread_id=agent.thread_id,
                job_ids=[job_id],
                status="done",
                model="test",
                usage={"input_tokens": 100, "cost_usd": cost, "cost_source": source},
                model_messages=None,
                started_at=finished - timedelta(seconds=9),
                finished_at=finished,
            )
        )
        await session.commit()


async def _age(routine_id: str, days: int) -> None:
    from sevn.domain.session import open_session
    from sevn.store.models import Routine

    async with open_session() as session:
        row = await session.get(Routine, routine_id)
        assert row is not None
        row.created_at = datetime.now(UTC) - timedelta(days=days)
        await session.commit()


async def test_upcoming_costs_candidates_and_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_modules(*_MODULES)
    now = datetime.now(UTC)
    async with connected(tmp_path, monkeypatch) as (_host, client):
        bot_id = await _bot(client, "Social")
        costly = await _create(client, bot_id, name="Costly", schedule="0 */12 * * *")
        quiet = await _create(client, bot_id, name="Quiet", schedule="0 9 * * *")
        unpriced = await _create(client, bot_id, name="Unpriced", schedule="0 8 * * *")
        paused = await _create(client, bot_id, name="Paused", schedule="0 7 * * *")
        ok(await _call(client, "routines.pause", routine_id=paused["id"]))
        for days in (1, 2, 3, 40):
            await _routine_turn(
                tmp_path, costly["id"], bot_id, now - timedelta(days=days), cost=0.5
            )
        await _routine_turn(
            tmp_path, quiet["id"], bot_id, now - timedelta(days=1), cost=0.1, silent=True
        )
        await _routine_turn(tmp_path, quiet["id"], bot_id, now - timedelta(days=20), cost=0.1)
        await _routine_turn(
            tmp_path, unpriced["id"], bot_id, now - timedelta(days=1), cost=None, source="unknown"
        )
        await _age(quiet["id"], 30)
        await _age(costly["id"], 30)
        body = ok(await _call(client, "fleet.overview"))
    upcoming = body["upcoming"]
    assert sorted(item["name"] for item in upcoming) == ["Costly", "Paused", "Quiet", "Unpriced"]
    assert upcoming[-1]["name"] == "Paused"
    byname = {item["name"]: item for item in upcoming}
    assert byname["Paused"]["status"] == "paused"
    assert byname["Paused"]["next_run"] is None
    costly_row = byname["Costly"]
    assert costly_row["runs_30d"] == 3
    assert costly_row["cost_30d_usd"] == pytest.approx(1.5)
    assert costly_row["cost_per_run_usd"] == pytest.approx(0.5)
    assert costly_row["runs_next_7d"] == 14
    assert costly_row["candidate_to_cancel"] is False
    assert costly_row["bot_name"] == "Social"
    quiet_row = byname["Quiet"]
    assert quiet_row["candidate_to_cancel"] is True
    assert quiet_row["last_outcome"] == "noop"
    unpriced_row = byname["Unpriced"]
    assert unpriced_row["cost_per_run_usd"] is None
    assert unpriced_row["unpriced_runs_30d"] == 1
    assert unpriced_row["candidate_to_cancel"] is False
    assert body["projection_7d_usd"] == pytest.approx(0.5 * 14 + 0.1 * 7)
    assert body["projection_unpriced"] == 1
    statuses = [item["status"] for item in upcoming]
    assert statuses.index("paused") > max(i for i, s in enumerate(statuses) if s == "active")
    next_runs = [item["next_run"] for item in upcoming if item["status"] == "active"]
    assert next_runs == sorted(next_runs)


async def test_spend_tile_shows_the_host_budget_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_modules(*_MODULES)
    monkeypatch.setenv("SEVN_BUDGETS__DAILY_USD_HOST", "1.0")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        bot_id = await _bot(client)
        await _spent_today(tmp_path, bot_id, 0.85)
        body = ok(await _call(client, "fleet.overview"))
        spend = next(tile for tile in body["kpis"] if tile["key"] == "spend_today")
        assert spend["budget_usd"] == pytest.approx(1.0)
        assert spend["level"] == "warn"
        await _spent_today(tmp_path, bot_id, 0.2)
        body = ok(await _call(client, "fleet.overview"))
        spend = next(tile for tile in body["kpis"] if tile["key"] == "spend_today")
        assert spend["level"] == "over"
