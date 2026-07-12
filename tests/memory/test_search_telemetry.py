"""Tests for memory search telemetry stub tables (`specs/31-memory-dreaming.md` §11)."""

from __future__ import annotations

import sqlite3

from sevn.memory.search_telemetry import (
    load_recall_weights,
    record_memory_recall_signal,
    record_memory_search_event,
)
from sevn.storage.migrate import MIGRATION_HEAD_VERSION, apply_migrations


def test_migration_16_tables_exist() -> None:
    # The migration head version is asserted in ``tests/storage/test_migrations.py``.
    # Here we only need the tables introduced by migration 16 to exist after the
    # full migration chain runs.
    assert MIGRATION_HEAD_VERSION >= 16
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    for name in ("memory_search_events", "memory_recall_signals"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        assert row is not None
    conn.close()


def test_record_and_load_recall_weights() -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    record_memory_recall_signal(
        conn,
        memory_key="k1",
        session_id="dm:u",
        recall_weight=0.75,
    )
    record_memory_search_event(
        conn,
        session_id="dm:u",
        query_text="prefs",
        source="all",
        result_count=2,
    )
    weights = load_recall_weights(conn)
    assert weights["k1"] == 0.75
    conn.close()
