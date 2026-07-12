"""Tests for ``traces.db`` migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sevn.agent.tracing.traces_migrate import (
    TRACES_MIGRATION_HEAD_VERSION,
    apply_traces_migrations,
    ensure_traces_db,
)
from sevn.storage.sqlite import connect_sqlite


def test_traces_migration_head() -> None:
    assert TRACES_MIGRATION_HEAD_VERSION == 2


def test_apply_traces_migrations_idempotent_memory() -> None:
    conn = sqlite3.connect(":memory:")
    apply_traces_migrations(conn)
    apply_traces_migrations(conn)
    ver = int(conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0])
    assert ver == TRACES_MIGRATION_HEAD_VERSION
    conn.close()


def test_trace_indexes_exist(tmp_path: Path) -> None:
    db = tmp_path / "traces.db"
    conn = connect_sqlite(db)
    apply_traces_migrations(conn)
    names = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='trace_events'",
        )
    }
    assert "ix_trace_events_session_turn_ts" in names
    assert "ix_trace_events_session_ts" in names
    conn.close()


def test_ensure_traces_db_creates_file(tmp_path: Path) -> None:
    p = tmp_path / "traces.db"
    ensure_traces_db(p)
    assert p.is_file()
