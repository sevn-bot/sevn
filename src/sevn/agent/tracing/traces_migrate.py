"""Versioned migrations for ``traces.db`` (Mission Control SQLite trace sink).

Module: sevn.agent.tracing.traces_migrate
Depends: sevn.storage.errors, sevn.storage.sqlite

Exports:
    apply_traces_migrations — idempotent runner for the trace database.
    ensure_trace_connection — open ``traces.db`` and apply migrations (caller closes).
    ensure_traces_db — connect, migrate, close for bootstrap.

Examples:
    >>> from sevn.agent.tracing.traces_migrate import TRACES_MIGRATION_HEAD_VERSION
    >>> TRACES_MIGRATION_HEAD_VERSION >= 1
    True
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Final

from sevn.storage.errors import MigrationError
from sevn.storage.sqlite import connect_sqlite

_MIGRATION_1: Final[tuple[str, ...]] = (
    """CREATE TABLE IF NOT EXISTS trace_events (
    span_id TEXT PRIMARY KEY NOT NULL,
    parent_span_id TEXT,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    tier TEXT,
    kind TEXT NOT NULL,
    ts_start_ns INTEGER NOT NULL,
    ts_end_ns INTEGER,
    status TEXT NOT NULL,
    attrs_json TEXT NOT NULL DEFAULT '{}'
)""",
    "CREATE INDEX IF NOT EXISTS ix_trace_events_session_turn_ts "
    "ON trace_events(session_id, turn_id, ts_start_ns)",
    "CREATE INDEX IF NOT EXISTS ix_trace_events_session_ts ON trace_events(session_id, ts_start_ns)",
)

# FTS5 search + hourly rollups (`specs/04-tracing.md` §10.7 Option-A bundle).
# The FTS table is contentless / external-content over ``trace_events`` so we
# do not duplicate row bytes; triggers keep ``rowid`` aligned with each event's
# ``rowid`` and index ``kind`` / ``attrs_json`` so Mission Control can search
# free-text terms ("error", a session id, a tool name) across the trace store.
# ``trace_rollups_hourly`` is bucketed per (UTC hour, kind) with an
# idempotent ``UNIQUE`` constraint — the writer uses
# ``INSERT ... ON CONFLICT(...) DO UPDATE`` so re-running over the same hour
# replaces, not double-counts.
_MIGRATION_2: Final[tuple[str, ...]] = (
    """CREATE VIRTUAL TABLE IF NOT EXISTS trace_events_fts USING fts5(
    kind,
    attrs_json,
    content='trace_events',
    content_rowid='rowid',
    tokenize='unicode61'
)""",
    # Keep the FTS index aligned with ``trace_events`` mutations.
    """CREATE TRIGGER IF NOT EXISTS trace_events_ai AFTER INSERT ON trace_events BEGIN
    INSERT INTO trace_events_fts(rowid, kind, attrs_json)
    VALUES (new.rowid, new.kind, new.attrs_json);
END""",
    """CREATE TRIGGER IF NOT EXISTS trace_events_ad AFTER DELETE ON trace_events BEGIN
    INSERT INTO trace_events_fts(trace_events_fts, rowid, kind, attrs_json)
    VALUES('delete', old.rowid, old.kind, old.attrs_json);
END""",
    """CREATE TRIGGER IF NOT EXISTS trace_events_au AFTER UPDATE ON trace_events BEGIN
    INSERT INTO trace_events_fts(trace_events_fts, rowid, kind, attrs_json)
    VALUES('delete', old.rowid, old.kind, old.attrs_json);
    INSERT INTO trace_events_fts(rowid, kind, attrs_json)
    VALUES (new.rowid, new.kind, new.attrs_json);
END""",
    """CREATE TABLE IF NOT EXISTS trace_rollups_hourly (
    hour_bucket_ns INTEGER NOT NULL,
    kind TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    error_count INTEGER NOT NULL,
    avg_duration_ns REAL,
    max_duration_ns INTEGER,
    updated_at_ns INTEGER NOT NULL,
    PRIMARY KEY (hour_bucket_ns, kind)
)""",
    "CREATE INDEX IF NOT EXISTS ix_trace_rollups_hourly_kind "
    "ON trace_rollups_hourly(kind, hour_bucket_ns)",
    "CREATE INDEX IF NOT EXISTS ix_trace_events_ts_start ON trace_events(ts_start_ns)",
)

TRACES_MIGRATIONS: Final[tuple[tuple[int, tuple[str, ...]], ...]] = (
    (1, _MIGRATION_1),
    (2, _MIGRATION_2),
)

TRACES_MIGRATION_HEAD_VERSION: Final[int] = max(v for v, _ in TRACES_MIGRATIONS)


def apply_traces_migrations(conn: sqlite3.Connection) -> None:
    """Apply pending ``traces.db`` migrations (separate from ``sevn.db``).

        Args:
    conn (sqlite3.Connection): Open SQLite connection.

        Raises:
    MigrationError: If a migration fails (transaction rolled back).

        Examples:
            >>> import sqlite3
            >>> c = sqlite3.connect(":memory:")
            >>> apply_traces_migrations(c)
            >>> c.execute("SELECT name FROM sqlite_master WHERE name='trace_events'").fetchone()[0]
            'trace_events'
            >>> c.close()
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    current = int(row[0]) if row else 0
    for version, statements in TRACES_MIGRATIONS:
        if version <= current:
            continue
        try:
            conn.execute("BEGIN IMMEDIATE")
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations(version) VALUES (?)",
                (version,),
            )
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK")
            raise MigrationError(f"Traces migration {version} failed: {exc}") from exc


def ensure_trace_connection(db_path: Path) -> sqlite3.Connection:
    """Open ``traces.db`` and apply owner spec migrations.

    Args:
        db_path (Path): Trace database path under ``.sevn``.

    Returns:
        sqlite3.Connection: Open connection; caller closes it.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> conn = ensure_trace_connection(Path(tempfile.mkdtemp()) / "traces.db")
        >>> conn.execute("SELECT name FROM sqlite_master WHERE name='trace_events'").fetchone()[0]
        'trace_events'
        >>> conn.close()
    """
    conn = connect_sqlite(db_path)
    apply_traces_migrations(conn)
    return conn


def ensure_traces_db(db_path: Path) -> None:
    """Create ``traces.db`` on disk (if needed) and apply all trace migrations.

        Args:
    db_path (Path): Path to ``traces.db``.

        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> p = Path(tempfile.mkdtemp()) / "traces.db"
            >>> ensure_traces_db(p)
            >>> p.exists()
            True
    """
    conn = connect_sqlite(db_path)
    try:
        apply_traces_migrations(conn)
    finally:
        conn.close()
