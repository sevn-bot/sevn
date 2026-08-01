"""Shared fixtures and migration contract for open-issues sweep Batch D (W17)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from sevn.storage.migrate import apply_migrations

# D13 - migration budget locked at W0 (anchor-freeze W0.8). W18-W22 own versions 25-29.
BATCH_D_BASELINE_HEAD: int = 24
BATCH_D_FIRST_IMPL_VERSION: int = 25
BATCH_D_LAST_IMPL_VERSION: int = 29


@dataclass(frozen=True)
class BatchDMigrationSlot:
    """One planned migration version for Batch D implementation waves."""

    version: int
    wave: str
    issue: int
    artifact: str
    table: str | None = None
    columns: tuple[tuple[str, str], ...] = ()


BATCH_D_MIGRATION_SLOTS: tuple[BatchDMigrationSlot, ...] = (
    BatchDMigrationSlot(
        version=25,
        wave="W18",
        issue=75,
        artifact="delivery-obligation ledger",
        table="delivery_obligations",
    ),
    BatchDMigrationSlot(
        version=26,
        wave="W19",
        issue=76,
        artifact="durable subagent result body",
        table="subagent_runs",
        columns=(("result_body", "TEXT"),),
    ),
    BatchDMigrationSlot(
        version=27,
        wave="W20",
        issue=77,
        artifact="per-run subagent transcript path",
        table="subagent_runs",
        columns=(("transcript_path", "TEXT"),),
    ),
    BatchDMigrationSlot(
        version=28,
        wave="W21",
        issue=85,
        artifact="cron execution audit history",
        table="cron_runs",
    ),
    BatchDMigrationSlot(
        version=29,
        wave="W22",
        issue=83,
        artifact="session export metadata (optional table)",
        table="session_export_jobs",
    ),
)

CRON_RUNS_COLUMNS: frozenset[str] = frozenset(
    {
        "job_id",
        "run_id",
        "claimed_at",
        "completed_at",
        "status",
        "transcript_path",
        "result_summary",
        "error",
    },
)


def memory_gateway_conn() -> sqlite3.Connection:
    """Open an in-memory migrated gateway SQLite handle."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def seed_gateway_session(
    conn: sqlite3.Connection,
    *,
    session_id: str = "sess-d",
    channel: str = "telegram",
    user_id: str = "42",
) -> None:
    """Insert one gateway session row for Batch D durability tests."""
    now = "2026-07-30T12:00:00+00:00"
    conn.execute(
        """
        INSERT INTO gateway_sessions(
            session_id, scope_key, channel, user_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (session_id, f"{channel}:{user_id}", channel, user_id, now, now),
    )
    conn.commit()


def insert_pending_assistant_message(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    content: str,
    message_id: int | None = None,
) -> int:
    """Insert a pending assistant message and return its row id."""
    now = "2026-07-30T12:00:01+00:00"
    if message_id is None:
        cur = conn.execute(
            """
            INSERT INTO gateway_messages(
                session_id, role, kind, content, visible_to_llm, status, created_at
            ) VALUES (?, 'assistant', 'message', ?, 1, 'pending', ?)
            """,
            (session_id, content, now),
        )
        conn.commit()
        return int(cur.lastrowid)
    conn.execute(
        """
        INSERT INTO gateway_messages(
            id, session_id, role, kind, content, visible_to_llm, status, created_at
        ) VALUES (?, ?, 'assistant', 'message', ?, 1, 'pending', ?)
        """,
        (message_id, session_id, content, now),
    )
    conn.commit()
    return message_id


def seed_bound_workspace(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    """Create a minimal bound workspace with migrated ``sevn.db``."""
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "content_root": str(tmp_path),
                "gateway": {"token": "test-token"},
            },
        ),
        encoding="utf-8",
    )
    dot_sevn = tmp_path / ".sevn"
    dot_sevn.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(dot_sevn / "sevn.db")
    apply_migrations(conn)
    return conn, tmp_path


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """Return whether ``name`` is a table in ``conn``."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, name: str) -> dict[str, str]:
    """Return ``PRAGMA table_info`` name→type map for ``name``."""
    return {str(r[1]): str(r[2]) for r in conn.execute(f"PRAGMA table_info({name})")}


@pytest.fixture
def batch_d_conn() -> sqlite3.Connection:
    """Migrated in-memory SQLite connection."""
    conn = memory_gateway_conn()
    seed_gateway_session(conn)
    yield conn
    conn.close()
