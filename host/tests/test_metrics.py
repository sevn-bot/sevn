"""Phase 6: bot-reported metrics with a source, a time and a freshness budget."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from support.chat import connected, fetch_all, load_modules, mint_id, ok, request


async def _bot(client: Any, name: str) -> str:
    frame, _earlier = await request(client, "bots.create", {"name": name, "op_id": mint_id("op_")})
    bot_id = ok(frame)["id"]
    assert isinstance(bot_id, str)
    return bot_id


def _tools(bot_id: str) -> dict[str, Any]:
    from sevn.tools.metric import metric_toolset
    from sevn.tools.registry import TurnDeps

    tools = metric_toolset(TurnDeps(bot_id=bot_id, agent_id="agent_x", turn_id="turn_x"))
    assert isinstance(tools, dict)
    return tools


async def _report(bot_id: str, **params: object) -> str:
    result = await _tools(bot_id)["metric.report"](**params)
    assert isinstance(result, str)
    return result


async def _overview(client: Any) -> dict[str, Any]:
    frame, _earlier = await request(client, "fleet.overview", {})
    return ok(frame)


def _iso(delta: timedelta) -> str:
    return (datetime.now(UTC) - delta).isoformat()


async def test_report_stores_a_point(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    load_modules("sevn.api.bots", "sevn.api.fleet")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        bot_id = await _bot(client, "Newsletter")
        answer = await _report(
            bot_id,
            key="subscribers",
            value=3210,
            source="Buttondown API /subscribers",
            unit="",
            label="Subscribers",
            as_of=_iso(timedelta(minutes=5)),
            freshness_minutes=1440,
            shareable=False,
        )
        assert answer == "ok"
        rows = fetch_all(
            tmp_path,
            "SELECT key, value, source, label, status, freshness_minutes, shareable "
            "FROM metric_points",
        )
    assert len(rows) == 1
    row = dict(rows[0])
    assert row == {
        "key": "subscribers",
        "value": 3210,
        "source": "Buttondown API /subscribers",
        "label": "Subscribers",
        "status": "ok",
        "freshness_minutes": 1440,
        "shareable": 0,
    }


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"key": "Has Spaces"}, "key"),
        ({"key": ""}, "key"),
        ({"source": "  "}, "source"),
        ({"as_of": "2026-11-01T10:00:00"}, "timezone"),
        ({"as_of": "tomorrow"}, "as_of"),
        ({"as_of": "2099-01-01T00:00:00+00:00"}, "future"),
        ({"freshness_minutes": 0}, "freshness"),
        ({"freshness_minutes": 60 * 24 * 31}, "freshness"),
        # Infinity or NaN would turn the dashboard frame into invalid JSON.
        ({"value": float("inf")}, "finite"),
        ({"value": float("-inf")}, "finite"),
        ({"value": float("nan")}, "finite"),
    ],
)
async def test_bad_reports_are_returned_to_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, params: dict[str, object], message: str
) -> None:
    load_modules("sevn.api.bots", "sevn.api.fleet")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        bot_id = await _bot(client, "Newsletter")
        base: dict[str, object] = {"key": "subscribers", "value": 1, "source": "api"}
        answer = await _report(bot_id, **{**base, **params})
        assert answer.startswith("invalid_params:")
        assert message in answer
        assert fetch_all(tmp_path, "SELECT id FROM metric_points") == []


async def test_tiles_show_fresh_stale_unavailable_and_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_modules("sevn.api.bots", "sevn.api.fleet")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        news = await _bot(client, "Newsletter")
        site = await _bot(client, "Site")
        await _report(
            news, key="subscribers", value=3100, source="api", as_of=_iso(timedelta(hours=26))
        )
        await _report(
            news,
            key="subscribers",
            value=3210,
            source="api",
            label="Subscribers",
            as_of=_iso(timedelta(minutes=10)),
        )
        await _report(
            site,
            key="visits",
            value=1100,
            unit="/day",
            source="Plausible",
            as_of=_iso(timedelta(hours=3)),
            freshness_minutes=60,
        )
        await _report(site, key="revenue", value=None, source="Stripe", unit="USD")
        body = await _overview(client)
    tiles = {tile["key"]: tile for tile in body["metrics"]}
    subscribers = tiles["subscribers"]
    assert subscribers["status"] == "ok"
    assert subscribers["value"] == 3210
    assert subscribers["delta_24h"] == pytest.approx(110)
    assert subscribers["label"] == "Subscribers"
    assert subscribers["bot_name"] == "Newsletter"
    assert subscribers["source"] == "api"
    assert datetime.fromisoformat(subscribers["as_of"]) < datetime.now(UTC)
    visits = tiles["visits"]
    assert visits["status"] == "stale"
    assert visits["value"] == 1100
    assert visits["unit"] == "/day"
    assert visits["delta_24h"] is None
    revenue = tiles["revenue"]
    assert revenue["status"] == "error"
    assert revenue["value"] is None
    assert next(tile["key"] for tile in body["metrics"]) == "revenue"


async def test_two_bots_disagreeing_is_shown_as_a_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_modules("sevn.api.bots", "sevn.api.fleet")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        first = await _bot(client, "Social")
        second = await _bot(client, "Research")
        await _report(first, key="followers", value=12400, source="X API")
        await _report(second, key="followers", value=12380, source="scrape")
        await _report(first, key="agreed", value=5, source="a")
        await _report(second, key="agreed", value=5, source="b")
        body = await _overview(client)
    tiles = {tile["key"]: tile for tile in body["metrics"]}
    followers = tiles["followers"]
    assert followers["status"] == "conflict"
    assert sorted((item["bot_name"], item["value"]) for item in followers["reports"]) == [
        ("Research", 12380),
        ("Social", 12400),
    ]
    assert tiles["agreed"]["status"] == "ok"


async def test_at_most_eight_tiles_newest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_modules("sevn.api.bots", "sevn.api.fleet")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        bot_id = await _bot(client, "Many")
        for index in range(10):
            await _report(
                bot_id,
                key=f"m{index}",
                value=index,
                source="s",
                as_of=_iso(timedelta(minutes=60 - index)),
            )
        body = await _overview(client)
    assert [tile["key"] for tile in body["metrics"]] == [f"m{index}" for index in range(9, 1, -1)]


async def test_long_history_reads_the_latest_point_and_its_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A month of hourly points: the tile shows the newest and the 24-48h change."""
    from sevn.domain.session import open_session
    from sevn.store.models import MetricPoint

    load_modules("sevn.api.bots", "sevn.api.fleet")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        bot_id = await _bot(client, "Newsletter")
        now = datetime.now(UTC)
        async with open_session() as session:
            for hour in range(24 * 30, 0, -1):
                moment = now - timedelta(hours=hour)
                session.add(
                    MetricPoint(
                        id=mint_id("met_"),
                        bot_id=bot_id,
                        key="subscribers",
                        label="subscribers",
                        value=float(10_000 - hour),
                        unit="",
                        source="api",
                        status="ok",
                        as_of=moment,
                        freshness_minutes=1440,
                        shareable=True,
                        created_at=moment,
                    )
                )
            await session.commit()
        body = await _overview(client)
        indexes = fetch_all(tmp_path, "PRAGMA index_list('metric_points')")
    tile = next(tile for tile in body["metrics"] if tile["key"] == "subscribers")
    assert tile["value"] == 9_999
    # Newest is 1 hour old; the last point at or before 24 hours before it is 25 hours old.
    assert tile["delta_24h"] == pytest.approx(24)
    assert any("key" in str(row["name"]) for row in indexes)
