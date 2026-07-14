"""SessionManager persistence tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from sevn.gateway.session_manager import SessionManager, _utc_now_iso
from sevn.gateway.util.timestamps import to_user_tz
from sevn.storage.migrate import apply_migrations
from sevn.storage.sqlite import connect_sqlite


@pytest.fixture
def memory_sess() -> tuple[sqlite3.Connection, SessionManager]:
    conn = connect_sqlite(Path(":memory:"))
    apply_migrations(conn)
    return conn, SessionManager(conn, message_cap=5)


@pytest.mark.asyncio
async def test_ensure_session_idempotent(
    memory_sess: tuple[sqlite3.Connection, SessionManager],
) -> None:
    conn, sm = memory_sess
    try:
        s1 = await sm.ensure_session(scope_key="a:1", channel="telegram", user_id="1")
        s2 = await sm.ensure_session(scope_key="a:1", channel="telegram", user_id="1")
        assert s1 == s2
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_message_cap_trims_oldest(
    memory_sess: tuple[sqlite3.Connection, SessionManager],
) -> None:
    conn, sm = memory_sess
    try:
        sid = await sm.ensure_session(scope_key="cap", channel="telegram", user_id="9")
        first_ids: list[int] = []
        for i in range(5):
            mid = await sm.add_message(
                sid,
                role="user",
                kind="message",
                content=f"m{i}",
                visible_to_llm=1,
                status="sent",
                turn_id="t-test",
            )
            first_ids.append(mid)
        total = conn.execute(
            "SELECT COUNT(*) FROM gateway_messages WHERE session_id = ?",
            (sid,),
        ).fetchone()[0]
        assert int(total) == 5
        await sm.add_message(
            sid,
            role="user",
            kind="message",
            content="overflow",
            visible_to_llm=1,
            status="sent",
            turn_id="t-test",
        )
        total2 = conn.execute(
            "SELECT COUNT(*) FROM gateway_messages WHERE session_id = ?",
            (sid,),
        ).fetchone()[0]
        assert int(total2) == 5
        oldest = conn.execute(
            "SELECT MIN(id) FROM gateway_messages WHERE session_id = ?",
            (sid,),
        ).fetchone()[0]
        assert int(oldest) > int(first_ids[0])
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_assistant_two_phase(memory_sess: tuple[sqlite3.Connection, SessionManager]) -> None:
    conn, sm = memory_sess
    try:
        sid = await sm.ensure_session(scope_key="ph", channel="webchat", user_id="2")
        mid = await sm.add_message(
            sid,
            role="assistant",
            kind="message",
            content="pending text",
            visible_to_llm=1,
            status="pending",
            turn_id="t-test",
        )
        row = conn.execute(
            "SELECT status FROM gateway_messages WHERE id = ?",
            (mid,),
        ).fetchone()
        assert row is not None
        assert str(row[0]) == "pending"
        await sm.set_message_status(mid, "sent")
        row2 = conn.execute(
            "SELECT status FROM gateway_messages WHERE id = ?",
            (mid,),
        ).fetchone()
        assert row2 is not None
        assert str(row2[0]) == "sent"
    finally:
        conn.close()


def test_now_iso_carries_local_offset_and_round_trips() -> None:
    """`_utc_now_iso` stamps the host-local offset (W4) and parses back cleanly.

    Service logs default to host-local time (``SEVN_LOG_TZ=local``); session
    message ``ts`` must match. The emitted string is offset-aware and survives a
    full round-trip through the renderer/parser used at display time.
    """
    iso = _utc_now_iso()
    parsed = datetime.fromisoformat(iso)
    # Offset-aware: matches the local zone the service logs render in.
    assert parsed.tzinfo is not None
    expected_offset = datetime.now().astimezone().utcoffset()
    assert parsed.utcoffset() == expected_offset
    # Round-trips through the display-time parser without raising/garbling.
    rendered = to_user_tz(iso, "UTC")
    assert rendered.endswith(" UTC")
    assert rendered != iso


@pytest.mark.asyncio
async def test_message_ts_is_offset_aware_and_parseable(
    memory_sess: tuple[sqlite3.Connection, SessionManager],
) -> None:
    """Stored message ``created_at`` (session-file ``ts`` source) is offset-aware.

    Existing UTC (``+00:00``) rows still parse via the same path, so this is a
    migrate-on-read change — no stored rows are rewritten.
    """
    conn, sm = memory_sess
    try:
        sid = await sm.ensure_session(scope_key="ts:1", channel="telegram", user_id="7")
        mid = await sm.add_message(
            sid,
            role="user",
            kind="message",
            content="hi",
            visible_to_llm=1,
            status="sent",
            turn_id="t-test",
        )
        row = conn.execute(
            "SELECT created_at FROM gateway_messages WHERE id = ?",
            (mid,),
        ).fetchone()
        assert row is not None
        created_at = str(row[0])
        parsed = datetime.fromisoformat(created_at)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == datetime.now().astimezone().utcoffset()
        # Legacy UTC rows must keep parsing (migrate-on-read, no rewrite).
        assert to_user_tz("2026-05-27T10:00:00+00:00", "UTC") == "10:00:00 UTC"
    finally:
        conn.close()
