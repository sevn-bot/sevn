"""Date-range filtering for session history queries (``since``/``until``).

Guards the timezone-correct comparison: gateway_messages store local-offset ISO
(``…+02:00``) while gateway_sessions store naive-UTC (space-separated), so the
queries normalise both sides with SQLite ``datetime()`` before comparing against
naive-UTC bounds from :func:`sevn.gateway.timestamps.resolve_time_range`.
"""

from __future__ import annotations

import sqlite3

import pytest

from sevn.gateway.sessions_query import (
    fetch_session_history,
    list_sessions,
    list_sessions_active_between,
    search_messages,
)
from sevn.storage.migrate import apply_migrations

_SID = "d" * 32


def _seed(conn: sqlite3.Connection, *, updated_at: str) -> None:
    conn.execute(
        """
        INSERT INTO gateway_sessions (session_id, scope_key, channel, user_id, created_at, updated_at)
        VALUES (?, 'web:owner', 'web', 'owner', ?, ?)
        """,
        (_SID, updated_at, updated_at),
    )


def _msg(conn: sqlite3.Connection, content: str, created_at: str) -> None:
    conn.execute(
        """
        INSERT INTO gateway_messages (session_id, role, kind, content, visible_to_llm, status, created_at)
        VALUES (?, 'user', 'message', ?, 1, 'sent', ?)
        """,
        (_SID, content, created_at),
    )


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    apply_migrations(c)
    # Naive-UTC session timestamp (space separator), like real gateway_sessions rows.
    _seed(c, updated_at="2026-07-02 15:00:00")
    # Local-offset ISO message timestamps, like real gateway_messages rows.
    _msg(c, "monday-note", "2026-07-01T12:00:00+02:00")
    _msg(c, "yesterday-note", "2026-07-02T12:00:00+02:00")
    _msg(c, "today-note", "2026-07-03T09:00:00+02:00")
    c.commit()
    return c


def test_fetch_session_history_since_until_filters_by_day(conn: sqlite3.Connection) -> None:
    data = fetch_session_history(
        conn, _SID, since="2026-07-02T00:00:00", until="2026-07-03T00:00:00"
    )
    bodies = [m["content"] for m in data["messages"]]
    assert bodies == ["yesterday-note"]


def test_fetch_session_history_since_only_is_open_ended(conn: sqlite3.Connection) -> None:
    data = fetch_session_history(conn, _SID, since="2026-07-02T00:00:00")
    bodies = [m["content"] for m in data["messages"]]
    assert bodies == ["yesterday-note", "today-note"]


def test_search_messages_date_only_no_query(conn: sqlite3.Connection) -> None:
    hits = search_messages(conn, "", since="2026-07-02T00:00:00", until="2026-07-03T00:00:00")
    assert [h["content"] for h in hits] == ["yesterday-note"]


def test_search_messages_query_plus_date(conn: sqlite3.Connection) -> None:
    hits = search_messages(conn, "note", since="2026-07-03T00:00:00")
    assert [h["content"] for h in hits] == ["today-note"]


def test_search_messages_requires_query_or_date(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="query or a date bound"):
        search_messages(conn, "")


def test_local_offset_message_bucketed_in_utc_day() -> None:
    """A message at 01:00 local (UTC+2) belongs to the *previous* UTC day."""
    c = sqlite3.connect(":memory:")
    apply_migrations(c)
    _seed(c, updated_at="2026-07-03 00:00:00")
    # 2026-07-03T01:00:00+02:00 == 2026-07-02T23:00:00 UTC → the UTC "yesterday".
    _msg(c, "edge", "2026-07-03T01:00:00+02:00")
    c.commit()
    in_utc_yesterday = search_messages(
        c, "", since="2026-07-02T00:00:00", until="2026-07-03T00:00:00"
    )
    in_utc_today = search_messages(c, "", since="2026-07-03T00:00:00", until="2026-07-04T00:00:00")
    assert [h["content"] for h in in_utc_yesterday] == ["edge"]
    assert in_utc_today == []


def test_list_sessions_date_range_filters_naive_utc(conn: sqlite3.Connection) -> None:
    hit = list_sessions(conn, date_from="2026-07-02T00:00:00", date_to="2026-07-03T00:00:00")
    assert len(hit) == 1
    miss = list_sessions(conn, date_from="2026-07-03T00:00:00", date_to="2026-07-04T00:00:00")
    assert miss == []


def test_active_between_finds_session_despite_updated_at_today() -> None:
    """Regression: a session bulk-bumped to today's updated_at but with messages
    yesterday must still surface for a 'yesterday' window (the shipped bug)."""
    c = sqlite3.connect(":memory:")
    apply_migrations(c)
    # updated_at is TODAY (as the gateway boot-reconcile leaves every session),
    # but the messages were created yesterday.
    _seed(c, updated_at="2026-07-03 13:41:00")
    _msg(c, "yesterday-work", "2026-07-02T14:00:00+02:00")
    c.commit()
    # list_sessions (updated_at based) misses it entirely...
    assert list_sessions(c, date_from="2026-07-02T00:00:00", date_to="2026-07-03T00:00:00") == []
    # ...list_sessions_active_between (created_at based) finds it.
    hits = list_sessions_active_between(c, since="2026-07-02T00:00:00", until="2026-07-03T00:00:00")
    assert len(hits) == 1
    assert hits[0]["session_id"] == _SID
    assert hits[0]["message_count"] == 1


def test_active_between_empty_when_no_messages_in_window(conn: sqlite3.Connection) -> None:
    assert (
        list_sessions_active_between(conn, since="2020-01-01T00:00:00", until="2020-01-02T00:00:00")
        == []
    )
