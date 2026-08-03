"""Batch B W7 RED — SQLite concurrency floor + durable trigger runs (#147; green after W9).

Contracts (`about-sevn.bot/specs/03-storage.md`, plan D13): ``connect_sqlite`` opens with a
30s busy timeout and ``synchronous=NORMAL`` on top of today's WAL + foreign keys, and
migration ``_MIGRATION_30`` adds a ``trigger_runs`` table whose rows outlive the process
that wrote them (`about-sevn.bot/specs/30-non-interactive-triggers.md`).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sevn.storage.migrate import MIGRATION_HEAD_VERSION, apply_migrations
from sevn.storage.sqlite import connect_sqlite

_TRIGGER_RUNS_HEAD_VERSION = 30
_BUSY_TIMEOUT_MS = 30_000
_SYNCHRONOUS_NORMAL = 1
_REQUIRED_TRIGGER_RUN_COLUMNS = frozenset(
    {"run_id", "correlation_id", "status", "created_at", "updated_at"},
)


def _migrated_conn(db_path: Path) -> sqlite3.Connection:
    conn = connect_sqlite(db_path)
    apply_migrations(conn)
    return conn


def _pragma(conn: sqlite3.Connection, name: str) -> object:
    return conn.execute(f"PRAGMA {name}").fetchone()[0]


def _insert_trigger_run(conn: sqlite3.Connection, *, run_id: str, status: str) -> None:
    conn.execute(
        "INSERT INTO trigger_runs (run_id, correlation_id, status, created_at, updated_at) "
        "VALUES (?, ?, ?, '2026-08-03T00:00:00Z', '2026-08-03T00:00:00Z')",
        (run_id, run_id, status),
    )
    conn.commit()


def test_connect_sqlite_keeps_wal_and_foreign_keys(tmp_path: Path) -> None:
    """Regression guard: the concurrency floor must not drop today's pragmas."""
    conn = connect_sqlite(tmp_path / "db" / "keep.sqlite")
    try:
        assert str(_pragma(conn, "journal_mode")).lower() == "wal"
        assert int(_pragma(conn, "foreign_keys")) == 1
    finally:
        conn.close()


def test_connect_sqlite_sets_busy_timeout_floor(tmp_path: Path) -> None:
    """Concurrent writers wait 30s for the lock instead of raising ``database is locked``."""
    conn = connect_sqlite(tmp_path / "db" / "busy.sqlite")
    try:
        assert int(_pragma(conn, "busy_timeout")) == _BUSY_TIMEOUT_MS
    finally:
        conn.close()


def test_connect_sqlite_sets_synchronous_normal(tmp_path: Path) -> None:
    """WAL + ``synchronous=NORMAL`` is the documented durability/throughput trade."""
    conn = connect_sqlite(tmp_path / "db" / "sync.sqlite")
    try:
        assert int(_pragma(conn, "synchronous")) == _SYNCHRONOUS_NORMAL
    finally:
        conn.close()


def test_connect_sqlite_uses_autocommit_isolation(tmp_path: Path) -> None:
    """``isolation_level=None`` keeps ``BEGIN IMMEDIATE`` in the migration runner honest."""
    conn = connect_sqlite(tmp_path / "db" / "iso.sqlite")
    try:
        assert conn.isolation_level is None
    finally:
        conn.close()


def test_migration_head_advances_to_trigger_runs_version() -> None:
    """D13: ``trigger_runs`` takes the next free version, one migration for this wave."""
    assert MIGRATION_HEAD_VERSION == _TRIGGER_RUNS_HEAD_VERSION


def test_trigger_runs_table_has_required_columns(tmp_path: Path) -> None:
    """Durable trigger state replaces the process-local ``app.state`` dict."""
    conn = _migrated_conn(tmp_path / "db" / "triggers.sqlite")
    try:
        cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(trigger_runs)").fetchall()}
        assert cols >= _REQUIRED_TRIGGER_RUN_COLUMNS
    finally:
        conn.close()


def test_trigger_runs_rejects_duplicate_run_id(tmp_path: Path) -> None:
    """Edge: a retried dispatch must not fork a second row for the same run."""
    conn = _migrated_conn(tmp_path / "db" / "dupe.sqlite")
    try:
        _insert_trigger_run(conn, run_id="run-dupe", status="accepted")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_trigger_run(conn, run_id="run-dupe", status="completed")
    finally:
        conn.close()


def test_trigger_run_status_survives_process_restart(tmp_path: Path) -> None:
    """The status written by one process is readable after the gateway restarts."""
    db_path = tmp_path / "db" / "restart.sqlite"
    first = _migrated_conn(db_path)
    try:
        _insert_trigger_run(first, run_id="run-restart", status="completed")
    finally:
        first.close()

    second = _migrated_conn(db_path)
    try:
        row = second.execute(
            "SELECT status FROM trigger_runs WHERE run_id = ?",
            ("run-restart",),
        ).fetchone()
        assert row is not None
        assert str(row[0]) == "completed"
    finally:
        second.close()


def test_pre_trigger_runs_database_migrates_forward(tmp_path: Path) -> None:
    """Migration fixture: a DB stopped one version short replays to the new head."""
    db_path = tmp_path / "db" / "upgrade.sqlite"
    seed = _migrated_conn(db_path)
    try:
        seed.execute(
            "DELETE FROM schema_migrations WHERE version >= ?",
            (_TRIGGER_RUNS_HEAD_VERSION,),
        )
        seed.execute("DROP TABLE IF EXISTS trigger_runs")
        seed.commit()
    finally:
        seed.close()

    upgraded = _migrated_conn(db_path)
    try:
        head = int(upgraded.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0])
        assert head == _TRIGGER_RUNS_HEAD_VERSION
        table = upgraded.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trigger_runs'",
        ).fetchone()
        assert table is not None
    finally:
        upgraded.close()
