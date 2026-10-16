"""Alembic head and the initial revision (K-MIG, D22)."""

from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
from pathlib import Path

from support.repo import repo_root


def test_migrations_single_head() -> None:
    completed = subprocess.run(
        ["make", "db-heads"],  # noqa: S607
        cwd=repo_root(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_upgrade_from_previous_head() -> None:
    matches = list((repo_root() / "host/src/sevn/store/migrations").rglob("0001_initial.py"))
    assert len(matches) == 1
    spec = importlib.util.spec_from_file_location("sevn_0001_initial", matches[0])
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision is None


async def test_upgrade_head_creates_tables(tmp_path: Path) -> None:
    from sevn.store.db import upgrade

    db_path = tmp_path / "sevn.db"
    await upgrade(f"sqlite+aiosqlite:///{db_path}")
    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"events", "op_log", "alembic_version"} <= tables
        journal = connection.execute("PRAGMA journal_mode").fetchone()
        assert journal is not None
        assert str(journal[0]).lower() == "wal"
        event_cols = {row[1] for row in connection.execute("PRAGMA table_info(events)")}
        op_cols = {row[1] for row in connection.execute("PRAGMA table_info(op_log)")}
    assert event_cols == {"seq", "type", "entity", "payload", "created_at"}
    assert op_cols == {"op_id", "method", "result", "created_at"}


async def test_models_match_migrations(tmp_path: Path) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext
    from sevn.store.db import upgrade
    from sevn.store.models import Base
    from sqlalchemy import create_engine

    db_path = tmp_path / "sevn.db"
    await upgrade(f"sqlite+aiosqlite:///{db_path}")
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()
    assert diff == []
