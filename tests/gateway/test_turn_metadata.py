"""Tests for ``sevn.gateway.turn.turn_metadata`` (`PROBLEMS.md` §7 / Step §7)."""

from __future__ import annotations

import sqlite3

import pytest

from sevn.gateway.turn.turn_metadata import (
    format_intent_footer_from_metadata,
    load_turn_metadata,
    record_turn_finished,
    record_turn_start,
)
from sevn.storage.migrate import apply_migrations


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    # ``gateway_turn_metadata.session_id`` FKs into ``gateway_sessions`` — seed
    # one row so the inserts don't trip foreign_keys=ON.
    conn.execute(
        """
        INSERT INTO gateway_sessions (
            session_id, scope_key, channel, user_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("s1", "telegram:1", "telegram", "1", "now", "now"),
    )
    conn.commit()
    return conn


def test_record_turn_start_inserts_in_flight_row() -> None:
    """Initial insert has ``status='in_flight'`` and ``finished_at IS NULL``."""
    conn = _memory_conn()
    record_turn_start(
        conn,
        turn_id="t1",
        session_id="s1",
        intent="NEW_REQUEST",
        tier="B",
        confidence=0.82,
        model_id="openai/gpt-tier-b",
    )
    row = load_turn_metadata(conn, "t1")
    assert row is not None
    assert row.turn_id == "t1"
    assert row.session_id == "s1"
    assert row.intent == "NEW_REQUEST"
    assert row.tier == "B"
    assert row.confidence == 0.82
    assert row.model_id == "openai/gpt-tier-b"
    assert row.status == "in_flight"
    assert row.finished_at is None
    assert row.started_at.endswith("+00:00")  # §4 tz-aware stamp


def test_record_turn_finished_updates_existing_row() -> None:
    """Calling finished after start stamps ``finished_at`` and updates status."""
    conn = _memory_conn()
    record_turn_start(
        conn,
        turn_id="t2",
        session_id="s1",
        intent="GREETING",
        tier="A",
        confidence=1.0,
    )
    record_turn_finished(conn, turn_id="t2", status="ok")
    row = load_turn_metadata(conn, "t2")
    assert row is not None
    assert row.status == "ok"
    assert row.finished_at is not None
    assert row.finished_at.endswith("+00:00")


def test_record_turn_finished_no_row_is_noop() -> None:
    """Stamping a non-existent turn_id is silently ignored."""
    conn = _memory_conn()
    record_turn_finished(conn, turn_id="ghost", status="ok")
    assert load_turn_metadata(conn, "ghost") is None


def test_record_turn_start_twice_updates_classification() -> None:
    """A re-triage in the cascade replaces (intent, tier, confidence)."""
    conn = _memory_conn()
    record_turn_start(
        conn,
        turn_id="t3",
        session_id="s1",
        intent="GREETING",
        tier="A",
        confidence=0.5,
    )
    record_turn_start(
        conn,
        turn_id="t3",
        session_id="s1",
        intent="NEW_REQUEST",
        tier="C",
        confidence=0.9,
        model_id="openai/gpt-tier-c",
    )
    row = load_turn_metadata(conn, "t3")
    assert row is not None
    assert row.intent == "NEW_REQUEST"
    assert row.tier == "C"
    assert row.confidence == 0.9
    assert row.model_id == "openai/gpt-tier-c"


def test_record_turn_start_clamps_confidence_to_unit_interval() -> None:
    """Out-of-range confidence is clamped to ``[0, 1]``."""
    conn = _memory_conn()
    record_turn_start(
        conn,
        turn_id="t4",
        session_id="s1",
        intent="NEW_REQUEST",
        tier="B",
        confidence=2.5,
    )
    row = load_turn_metadata(conn, "t4")
    assert row is not None
    assert row.confidence == 1.0
    record_turn_start(
        conn,
        turn_id="t5",
        session_id="s1",
        intent="NEW_REQUEST",
        tier="B",
        confidence=-0.5,
    )
    row = load_turn_metadata(conn, "t5")
    assert row is not None
    assert row.confidence == 0.0


def test_load_turn_metadata_missing_returns_none() -> None:
    """Missing rows return ``None`` (caller decides default)."""
    conn = _memory_conn()
    assert load_turn_metadata(conn, "no-such-turn") is None


def test_record_turn_start_rejects_orphan_session_when_fk_on() -> None:
    """Foreign-key constraint catches turn_ids pointing at non-existent sessions."""
    conn = _memory_conn()
    with pytest.raises(sqlite3.IntegrityError):
        record_turn_start(
            conn,
            turn_id="orphan",
            session_id="no-such-session",
            intent="NEW_REQUEST",
            tier="B",
            confidence=0.5,
        )


def test_format_intent_footer_matches_legacy_shape() -> None:
    """The formatter mirrors the historical footer body produced from
    ``routing_footer.format_routing_footer`` — no surprises for users
    who already had ``show_intent_footer`` on."""
    conn = _memory_conn()
    record_turn_start(
        conn,
        turn_id="t6",
        session_id="s1",
        intent="GREETING",
        tier="A",
        confidence=0.95,
    )
    row = load_turn_metadata(conn, "t6")
    assert row is not None
    assert format_intent_footer_from_metadata(row) == ("intent=GREETING · tier=A · conf=0.95")
