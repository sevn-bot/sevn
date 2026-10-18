"""History search and cursor reads survive compaction (green after W7)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from support.botcore import arm_configured, upgrade_home
from support.chat import fetch_all, insert_turn, mint_id

pytestmark = pytest.mark.xfail(
    reason="green after W7: history tools",
    strict=False,
)


async def _thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[object, object, str]:
    from sevn.domain.agents import AgentService
    from sevn.domain.bots import BotService

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Nimbus")
    agent = await AgentService().spawn(bot.id)
    turn_id = await insert_turn(
        tmp_path,
        agent_id=agent.id,
        thread_id=agent.thread_id,
        job_id=mint_id("job_"),
        status="done",
        model_messages=[],
    )
    return bot, agent, turn_id


def _insert(home: Path, agent: object, turn_id: str, text: str, created_at: str) -> str:
    message_id = mint_id("msg_")
    parts = json.dumps([{"type": "text", "text": text}])
    with sqlite3.connect(home / "sevn.db") as connection:
        connection.execute(
            """
            INSERT INTO messages (
                id, thread_id, turn_id, agent_id, role, author, parts, created_at
            ) VALUES (?, ?, ?, ?, 'user', 'user', ?, ?)
            """,
            (message_id, agent.thread_id, turn_id, agent.id, parts, created_at),
        )
        connection.commit()
    return message_id


async def test_originals_remain_searchable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fakes.models import function_model
    from sevn.runtime.compaction import compact_messages
    from sevn.runtime.models import use_model
    from sevn.tools.history import search

    bot, agent, turn_id = await _thread(tmp_path, monkeypatch)
    _insert(tmp_path, agent, turn_id, "history-needle-alpha", "2026-06-01T00:00:00+00:00")
    _insert(tmp_path, agent, turn_id, "history-needle-beta", "2026-06-01T00:01:00+00:00")
    use_model(function_model([{"kind": "text", "text": "summary-of-older"}]))
    try:
        await compact_messages([], model_window=1000, estimated_tokens=800)
    finally:
        use_model(None)
    hits = await search(str(bot.id), "history-needle-alpha")
    assert hits
    assert "history-needle-alpha" in hits[0].text
    stored = fetch_all(
        tmp_path,
        "SELECT id FROM messages WHERE parts LIKE ?",
        ("%history-needle-alpha%",),
    )
    assert stored


async def test_history_read_by_cursor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.tools.history import read, search

    bot, agent, turn_id = await _thread(tmp_path, monkeypatch)
    first_id = _insert(
        tmp_path, agent, turn_id, "history-needle-alpha", "2026-06-01T00:00:00+00:00"
    )
    _insert(tmp_path, agent, turn_id, "history-needle-beta", "2026-06-01T00:01:00+00:00")
    hits = await search(str(bot.id), "history-needle-alpha")
    assert hits[0].message_id == first_id
    page = await read(message_id=first_id)
    assert page.text == "history-needle-alpha"
    assert isinstance(page.cursor, str) and page.cursor != ""
    nxt = await read(cursor=page.cursor)
    assert nxt.text == "history-needle-beta"


async def test_history_tools_are_deferred(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sevn.tools.history
    from sevn.tools.registry import toolsets_for

    bot, _agent, _turn = await _thread(tmp_path, monkeypatch)
    assert sevn.tools.history.__name__ == "sevn.tools.history"
    eager: set[str] = set()
    deferred: set[str] = set()
    for item in toolsets_for(bot):
        eager.update(item.eager)
        deferred.update(item.deferred)
    assert {"history.search", "history.read"} <= deferred
    assert "history.search" not in eager
    assert "history.read" not in eager
