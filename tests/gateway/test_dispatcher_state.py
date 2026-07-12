"""``dispatcher_state`` insert validation and expiry sweeper tests."""

from __future__ import annotations

import json
import sqlite3
import time

import pytest

from sevn.config.defaults import DEFAULT_DISPATCHER_STATE_TTL_SECONDS
from sevn.gateway.dispatcher_state import (
    dispatcher_state_ttl_for_kind,
    insert_dispatcher_state,
    sweep_expired_dispatcher_state,
)
from sevn.storage.migrate import apply_migrations


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    return conn


def test_insert_unknown_kind_raises() -> None:
    conn = _conn()
    payload = json.dumps({"v": 1}, separators=(",", ":"))
    with pytest.raises(ValueError, match="unknown dispatcher_state kind"):
        insert_dispatcher_state(
            conn,
            token="bad-kind",
            kind="not_a_real_kind",
            user_id=0,
            chat_id=1,
            topic_id=None,
            payload_json=payload,
            ttl_seconds=60,
        )


def test_per_kind_ttl_honoured_by_sweeper() -> None:
    conn = _conn()
    payload = json.dumps({"v": 1}, separators=(",", ":"))
    base = int(time.time())
    short_ttl = int(DEFAULT_DISPATCHER_STATE_TTL_SECONDS["plan_approval"])
    long_ttl = int(DEFAULT_DISPATCHER_STATE_TTL_SECONDS["menu"])

    insert_dispatcher_state(
        conn,
        token="tok-short",
        kind="plan_approval",
        user_id=1,
        chat_id=1,
        topic_id=None,
        payload_json=payload,
        ttl_seconds=short_ttl,
    )
    insert_dispatcher_state(
        conn,
        token="tok-long",
        kind="menu",
        user_id=1,
        chat_id=1,
        topic_id=None,
        payload_json=payload,
        ttl_seconds=long_ttl,
    )

    short_row = conn.execute(
        "SELECT expires_at FROM dispatcher_state WHERE token = 'tok-short'",
    ).fetchone()
    long_row = conn.execute(
        "SELECT expires_at FROM dispatcher_state WHERE token = 'tok-long'",
    ).fetchone()
    assert short_row is not None
    assert long_row is not None
    assert int(short_row[0]) - base <= short_ttl + 2
    assert int(long_row[0]) - base >= long_ttl - 2

    sweep_at = base + short_ttl + 1
    deleted = sweep_expired_dispatcher_state(conn, now=sweep_at)
    assert deleted >= 1

    remaining = {str(r[0]) for r in conn.execute("SELECT token FROM dispatcher_state").fetchall()}
    assert "tok-short" not in remaining
    assert "tok-long" in remaining


def test_dispatcher_state_ttl_for_kind_defaults() -> None:
    assert dispatcher_state_ttl_for_kind("secret_wizard") == 7200
    assert dispatcher_state_ttl_for_kind("webapp_share") == 3600
    assert dispatcher_state_ttl_for_kind("callback_overflow") == 86400
