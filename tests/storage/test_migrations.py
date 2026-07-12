"""Tests for storage migrations and SQLite open helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sevn.storage import (
    MIGRATION_HEAD_VERSION,
    apply_migrations,
    connect_sqlite,
    open_sevn_sqlite,
    sevn_db_path,
    traces_sqlite_path,
)


def test_migration_head_matches_bundle() -> None:
    assert MIGRATION_HEAD_VERSION == 22


def test_apply_migrations_idempotent_memory() -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    apply_migrations(conn)
    ver = int(conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0])
    assert ver == MIGRATION_HEAD_VERSION
    conn.close()


def test_active_run_snapshots_table_exists(tmp_path: Path) -> None:
    conn = connect_sqlite(tmp_path / "db" / "test.db")
    apply_migrations(conn)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='active_run_snapshots'",
    ).fetchone()
    assert row is not None
    conn.close()


def test_open_sevn_sqlite_under_dot_sevn(tmp_path: Path) -> None:
    dot = tmp_path / ".sevn"
    dot.mkdir()
    conn = open_sevn_sqlite(dot)
    try:
        assert sevn_db_path(dot).exists()
        assert (
            int(conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0])
            == MIGRATION_HEAD_VERSION
        )
    finally:
        conn.close()


def test_traces_sqlite_path_suffix() -> None:
    p = traces_sqlite_path(Path("/z/.sevn"))
    assert p.name == "traces.db"


def test_gateway_tables_exist(tmp_path: Path) -> None:
    conn = connect_sqlite(tmp_path / "d" / "gw.sqlite")
    apply_migrations(conn)
    names = {
        str(r[0])
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'gateway_%'",
        ).fetchall()
    }
    assert "gateway_sessions" in names
    assert "gateway_messages" in names
    assert "gateway_media_tokens" in names
    conn.close()


def test_cursor_cloud_jobs_table_exists(tmp_path: Path) -> None:
    conn = connect_sqlite(tmp_path / "d" / "cc.sqlite")
    apply_migrations(conn)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='cursor_cloud_jobs'",
    ).fetchone()
    assert row is not None
    conn.close()


def test_dispatcher_callbacks_table_exists(tmp_path: Path) -> None:
    conn = connect_sqlite(tmp_path / "d" / "dcb.sqlite")
    apply_migrations(conn)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dispatcher_callbacks'",
    ).fetchone()
    assert row is not None
    conn.close()


def test_telegram_topic_names_table_exists(tmp_path: Path) -> None:
    conn = connect_sqlite(tmp_path / "d" / "tg.sqlite")
    apply_migrations(conn)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='telegram_topic_names'",
    ).fetchone()
    assert row is not None
    conn.close()


def test_dispatcher_state_table_exists(tmp_path: Path) -> None:
    conn = connect_sqlite(tmp_path / "d" / "ds.sqlite")
    apply_migrations(conn)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dispatcher_state'",
    ).fetchone()
    assert row is not None
    conn.close()


def test_openui_tokens_table_exists(tmp_path: Path) -> None:
    conn = connect_sqlite(tmp_path / "d" / "ou.sqlite")
    apply_migrations(conn)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='openui_tokens'",
    ).fetchone()
    assert row is not None
    conn.close()


def test_active_run_snapshots_has_awaiting_callback_column(tmp_path: Path) -> None:
    conn = connect_sqlite(tmp_path / "d" / "cb.sqlite")
    apply_migrations(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(active_run_snapshots)").fetchall()}
    assert "awaiting_callback_token" in cols
    conn.close()


def test_triage_decisions_table_exists(tmp_path: Path) -> None:
    conn = connect_sqlite(tmp_path / "d" / "trg.sqlite")
    apply_migrations(conn)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='triage_decisions'",
    ).fetchone()
    assert row is not None
    conn.close()


def test_turn_replay_dedupe_table_exists(tmp_path: Path) -> None:
    conn = connect_sqlite(tmp_path / "d" / "replay.sqlite")
    apply_migrations(conn)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='turn_replay_dedupe'",
    ).fetchone()
    assert row is not None
    conn.close()


def test_pending_plans_table_exists(tmp_path: Path) -> None:
    conn = connect_sqlite(tmp_path / "d" / "plans.sqlite")
    apply_migrations(conn)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pending_plans'",
    ).fetchone()
    assert row is not None
    conn.close()


def test_memory_kv_table_exists(tmp_path: Path) -> None:
    conn = connect_sqlite(tmp_path / "d" / "mem.sqlite")
    apply_migrations(conn)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memory'",
    ).fetchone()
    assert row is not None
    conn.close()


def test_trigger_tables_exist(tmp_path: Path) -> None:
    conn = connect_sqlite(tmp_path / "d" / "tr.sqlite")
    apply_migrations(conn)
    for name in ("trigger_webhook_dedupe", "trigger_cron_jobs"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        assert row is not None
    conn.close()


def test_skills_chronic_failure_table_exists(tmp_path: Path) -> None:
    """Migration 15 — ``skills`` denormalised ``chronic_skill_failure`` flag + partial index."""
    conn = connect_sqlite(tmp_path / "d" / "sk.sqlite")
    apply_migrations(conn)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='skills'",
    ).fetchone()
    assert row is not None
    cols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(skills)").fetchall()}
    assert cols["chronic_skill_failure"] == "INTEGER"
    idx = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='ix_skills_chronic_failure'",
    ).fetchone()
    assert idx is not None
    conn.execute(
        "INSERT INTO skills (workspace_id, skill_name, failure_count, chronic_skill_failure, "
        "failure_timestamps_json, updated_at_ns) VALUES ('ws1', 'demo', 3, 1, '[]', 1)",
    )
    conn.commit()
    flagged = conn.execute(
        "SELECT skill_name FROM skills WHERE workspace_id = 'ws1' AND chronic_skill_failure = 1",
    ).fetchone()
    assert flagged is not None
    assert flagged[0] == "demo"
    conn.close()


def test_structured_feedback_table_exists(tmp_path: Path) -> None:
    """Migration 17 — ``structured_feedback`` free-text rows + indexes."""
    conn = connect_sqlite(tmp_path / "d" / "sf.sqlite")
    apply_migrations(conn)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='structured_feedback'",
    ).fetchone()
    assert row is not None
    cols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(structured_feedback)").fetchall()}
    assert cols["feedback_id"] == "TEXT"
    assert cols["target_turn_id"] == "TEXT"
    assert cols["body_text"] == "TEXT"
    for idx_name in (
        "ix_structured_feedback_turn",
        "ix_structured_feedback_user_created",
        "ix_structured_feedback_submission_key",
    ):
        idx = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (idx_name,),
        ).fetchone()
        assert idx is not None
    conn.close()


def test_trajectory_fact_table_exists(tmp_path: Path) -> None:
    """Migration 18 — ``trajectory_fact`` denormalised turn rows."""
    conn = connect_sqlite(tmp_path / "d" / "traj.sqlite")
    apply_migrations(conn)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='trajectory_fact'",
    ).fetchone()
    assert row is not None
    cols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(trajectory_fact)").fetchall()}
    assert cols["turn_id"] == "TEXT"
    assert cols["signals_json"] == "TEXT"
    conn.close()


def test_self_improve_tables_exist(tmp_path: Path) -> None:
    conn = connect_sqlite(tmp_path / "d" / "si.sqlite")
    apply_migrations(conn)
    for name in ("self_improve_jobs", "feedback_events"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        assert row is not None
    conn.close()


def test_active_run_snapshots_tier_check_constraint(tmp_path: Path) -> None:
    """Migration 8 rebuild adds ``tier`` CHECK including ``triager``."""
    conn = connect_sqlite(tmp_path / "d" / "tier.sqlite")
    apply_migrations(conn)
    conn.execute(
        "INSERT INTO active_run_snapshots (run_id, session_id, tier, created_at_ns, updated_at_ns) "
        "VALUES ('r1', 's1', 'triager', 1, 1)",
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO active_run_snapshots (run_id, session_id, tier, created_at_ns, updated_at_ns) "
            "VALUES ('r2', 's1', 'oops', 1, 1)",
        )
    conn.close()
