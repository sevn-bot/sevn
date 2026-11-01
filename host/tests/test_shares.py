"""Phase 6: read-only share links. A redacted snapshot over plain HTTP."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

_SECRET_TEXTS = (
    "Which subject line for the secret launch?",
    "Draft the private acquisition memo",
    "the acquisition is closing on Friday",
    "rm -rf ./confidential",
    "Scan the confidential inbox for offers",
    "revenue-private",
)


async def _seed(home: Path) -> dict[str, str]:
    from sevn.domain.agents import AgentService
    from sevn.domain.bots import BotService
    from sevn.domain.metrics import report
    from sevn.domain.routines import RoutineService
    from sevn.domain.session import open_session
    from sevn.store.models import Message, PendingRequest, Turn

    atlas = await BotService().create("Atlas")
    nimbus = await BotService().create("Nimbus")
    lane = await AgentService().spawn(atlas.id, title="Draft the private acquisition memo")
    other = await AgentService().spawn(nimbus.id, title="Nimbus lane")
    now = datetime.now(UTC)
    async with open_session() as session:
        for agent, status in ((lane, "done"), (other, "done"), (lane, "waiting")):
            turn_id = f"turn_{agent.id}_{status}"
            session.add(
                Turn(
                    id=turn_id,
                    agent_id=agent.id,
                    thread_id=agent.thread_id,
                    job_ids=[],
                    status=status,
                    model="m",
                    usage={"input_tokens": 10, "cost_usd": 0.2, "cost_source": "price_table"},
                    model_messages=None,
                    started_at=now - timedelta(minutes=5),
                    finished_at=now if status == "done" else None,
                )
            )
            await session.flush()
            if status == "done":
                session.add(
                    Message(
                        id=f"msg_{turn_id}",
                        thread_id=agent.thread_id,
                        turn_id=turn_id,
                        agent_id=agent.id,
                        role="assistant",
                        author=agent.bot_id,
                        parts=[{"type": "text", "text": "the acquisition is closing on Friday"}],
                        created_at=now,
                    )
                )
            else:
                session.add(
                    PendingRequest(
                        id="pend_q",
                        turn_id=turn_id,
                        agent_id=agent.id,
                        kind="question",
                        tool_call_id=None,
                        payload={"text": "Which subject line for the secret launch?"},
                        answer=None,
                        status="waiting",
                        created_at=now,
                        resolved_at=None,
                    )
                )
                session.add(
                    PendingRequest(
                        id="pend_a",
                        turn_id=turn_id,
                        agent_id=agent.id,
                        kind="approval",
                        tool_call_id="call_1",
                        payload={"name": "shell", "args": {"command": "rm -rf ./confidential"}},
                        answer=None,
                        status="waiting",
                        created_at=now,
                        resolved_at=None,
                    )
                )
        await session.commit()
    await RoutineService().create(
        atlas.id,
        name="Inbox sweep",
        schedule="0 * * * *",
        timezone="UTC",
        text="Scan the confidential inbox for offers",
    )
    await RoutineService().create(
        nimbus.id, name="Nimbus digest", schedule="0 9 * * *", timezone="UTC", text="Digest."
    )
    await report(atlas.id, key="subscribers", value=3210, source="Buttondown")
    await report(atlas.id, key="revenue-private", value=99000, source="Stripe", shareable=False)
    await report(nimbus.id, key="followers", value=12400, source="X API")
    return {"atlas": atlas.id, "nimbus": nimbus.id}


def _create(**kwargs: Any) -> tuple[dict[str, Any], str]:
    from sevn.domain.shares import ShareService

    record, path = asyncio.run(ShareService().create(**kwargs))
    return record.model_dump(mode="json"), path


def _rows(home: Path, sql: str, args: tuple[object, ...] = ()) -> list[sqlite3.Row]:
    with sqlite3.connect(home / "sevn.db") as connection:
        connection.row_factory = sqlite3.Row
        return list(connection.execute(sql, args))


def test_a_share_link_serves_a_redacted_snapshot(
    host_app: tuple[object, str, object], tmp_path: Path
) -> None:
    _app, _token, client = host_app
    asyncio.run(_seed(tmp_path))
    record, path = _create(label="For the editor", bot_id=None, expires_in_hours=24)
    share_id = record["id"]
    secret = path.rsplit("/", 1)[-1]
    assert path == f"/share/{share_id}/{secret}"
    assert len(secret) >= 40
    stored = _rows(tmp_path, "SELECT secret_hash FROM share_links WHERE id = ?", (share_id,))
    assert secret not in stored[0]["secret_hash"]
    response = client.get(f"{path}/data")  # type: ignore[attr-defined]
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    body = response.json()
    text = json.dumps(body)
    for secret_text in _SECRET_TEXTS:
        assert secret_text not in text, secret_text
    assert body["label"] == "For the editor"
    assert body["scope_bot_name"] is None
    assert {item["name"] for item in body["bots"]} == {"Atlas", "Nimbus"}
    assert body["waiting"] == 2
    assert body["finished_24h"] == {"done": 2, "failed": 0}
    assert {tile["key"] for tile in body["metrics"]} == {"subscribers", "followers"}
    assert {item["name"] for item in body["upcoming"]} == {"Inbox sweep", "Nimbus digest"}
    assert {tile["key"] for tile in body["kpis"]} == {
        "spend_today",
        "tokens_today",
        "waiting",
        "running",
    }
    opened = _rows(
        tmp_path, "SELECT opens, last_opened_at FROM share_links WHERE id = ?", (share_id,)
    )
    assert opened[0]["opens"] == 1
    assert opened[0]["last_opened_at"] is not None


def test_a_bot_scoped_link_shows_only_that_bot(
    host_app: tuple[object, str, object], tmp_path: Path
) -> None:
    _app, _token, client = host_app
    bots = asyncio.run(_seed(tmp_path))
    _record, path = _create(label="Nimbus only", bot_id=bots["nimbus"], expires_in_hours=1)
    body = client.get(f"{path}/data").json()  # type: ignore[attr-defined]
    assert body["scope_bot_name"] == "Nimbus"
    assert [item["name"] for item in body["bots"]] == ["Nimbus"]
    assert [tile["key"] for tile in body["metrics"]] == ["followers"]
    assert [item["name"] for item in body["upcoming"]] == ["Nimbus digest"]
    assert {row["bot_id"] for row in body["activity"]} <= {bots["nimbus"]}
    assert body["waiting"] == 0
    assert body["finished_24h"] == {"done": 1, "failed": 0}
    assert body["kpis"] == []
    assert body["projection_7d_usd"] is None
    assert "Atlas" not in json.dumps(body)


def test_wrong_revoked_and_expired_links_are_not_found(
    host_app: tuple[object, str, object], tmp_path: Path
) -> None:
    from sevn.domain.shares import ShareService

    _app, _token, client = host_app
    asyncio.run(_seed(tmp_path))
    record, path = _create(label="Soon gone", bot_id=None, expires_in_hours=1)
    share_id = record["id"]
    responses = [
        client.get(f"/share/{share_id}/wrong-secret/data"),  # type: ignore[attr-defined]
        client.get(f"/share/shr_missing/{path.rsplit('/', 1)[-1]}/data"),  # type: ignore[attr-defined]
    ]
    asyncio.run(ShareService().revoke(share_id))
    responses.append(client.get(f"{path}/data"))  # type: ignore[attr-defined]
    _second, live = _create(label="Expired", bot_id=None, expires_in_hours=1)
    with sqlite3.connect(tmp_path / "sevn.db") as connection:
        connection.execute(
            "UPDATE share_links SET expires_at = ? WHERE id = ?",
            ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(), live.split("/")[2]),
        )
        connection.commit()
    responses.append(client.get(f"{live}/data"))  # type: ignore[attr-defined]
    for response in responses:
        assert response.status_code == 404
        assert response.json() == {"error": "not found"}
    opens = _rows(tmp_path, "SELECT opens FROM share_links WHERE id = ?", (share_id,))
    assert opens[0]["opens"] == 0


def test_the_share_page_is_the_spa(host_app: tuple[object, str, object]) -> None:
    _app, _token, client = host_app
    response = client.get("/share/shr_x/secret")  # type: ignore[attr-defined]
    assert response.status_code == 200
    assert "<title>sevn</title>" in response.text
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"label": "", "bot_id": None, "expires_in_hours": 24},
        {"label": "x", "bot_id": None, "expires_in_hours": 0},
        {"label": "x", "bot_id": None, "expires_in_hours": 24 * 31},
        {"label": "x", "bot_id": "bot_missing", "expires_in_hours": 24},
    ],
)
def test_bad_share_links_are_refused(
    host_app: tuple[object, str, object], kwargs: dict[str, Any]
) -> None:
    from sevn.domain.errors import DomainError

    with pytest.raises(DomainError) as caught:
        _create(**kwargs)
    assert caught.value.code in {"invalid_params", "not_found"}


def test_list_and_revoke_from_the_protocol(
    host_app: tuple[object, str, object], tmp_path: Path
) -> None:
    from sevn.domain.shares import ShareService

    asyncio.run(_seed(tmp_path))
    record, _path = _create(label="Listed", bot_id=None, expires_in_hours=24)
    listed = asyncio.run(ShareService().list())
    assert [item.id for item in listed] == [record["id"]]
    assert listed[0].status == "active"
    revoked = asyncio.run(ShareService().revoke(record["id"]))
    assert revoked.status == "revoked"
    assert revoked.revoked_at is not None
