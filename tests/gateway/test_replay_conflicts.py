"""Turn replay conflict contract used by gateway HTTP (`specs/16-harness-discipline.md` section 2.3).

When ``POST .../turns/{turn_id}/replay`` is implemented in the gateway, the
handler should return **409** if ``session_has_active_run_for_replay`` is true
for the session. These tests lock that precondition independent of routing.
"""

from __future__ import annotations

import sqlite3

import pytest

from sevn.agent.harness.snapshots import session_has_active_run_for_replay
from sevn.storage.migrate import apply_migrations


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    return conn


def test_replay_conflict_contract_active_blocks() -> None:
    conn = _db()
    conn.execute(
        """INSERT INTO active_run_snapshots (
            run_id, session_id, tier, plan_state, in_flight_tools,
            excerpt, status, created_at_ns, updated_at_ns
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("gw-r1", "gw-sess", "C", "{}", "[]", "x", "active", 1, 2),
    )
    conn.commit()
    assert session_has_active_run_for_replay(conn, "gw-sess") is True


@pytest.mark.parametrize("status", ["sent", "cancelled", "failed", "abandoned"])
def test_replay_conflict_contract_terminal_does_not_block(status: str) -> None:
    conn = _db()
    conn.execute(
        """INSERT INTO active_run_snapshots (
            run_id, session_id, tier, plan_state, in_flight_tools,
            excerpt, status, created_at_ns, updated_at_ns
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("gw-r2", "gw-sess2", "B", "{}", "[]", "x", status, 1, 2),
    )
    conn.commit()
    assert session_has_active_run_for_replay(conn, "gw-sess2") is False
