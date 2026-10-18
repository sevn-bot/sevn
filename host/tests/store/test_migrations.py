"""Alembic head and the initial revision (K-MIG, D22)."""

from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
from pathlib import Path

import pytest
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


def test_revisions_are_frozen_ddl() -> None:
    versions = repo_root() / "host/src/sevn/store/migrations/versions"
    for name in ("0001_initial.py", "0002_bots_agents.py"):
        text = (versions / name).read_text()
        assert "sevn.store.models" not in text
        assert "__table__" not in text
        assert "op.create_table" in text
    agents = (versions / "0002_bots_agents.py").read_text()
    assert 'sa.Column("isolation"' in agents


def test_find_alembic_ini_is_not_tied_to_editable_depth(tmp_path: Path) -> None:
    from sevn.store.db import _find_alembic_ini, _migrations_dir

    start = tmp_path / "pkg" / "store" / "db.py"
    start.parent.mkdir(parents=True)
    ini = tmp_path / "alembic.ini"
    location = _migrations_dir().resolve().as_posix()
    ini.write_text(f"[alembic]\nscript_location = {location}\n")
    assert _find_alembic_ini(start) == ini.resolve()


def test_foreign_ancestor_alembic_ini_uses_packaged_fallback(tmp_path: Path) -> None:
    from sevn.store.db import _alembic_config, _migrations_dir

    start = tmp_path / "proj" / ".venv" / "lib" / "sevn" / "store" / "db.py"
    start.parent.mkdir(parents=True)
    (tmp_path / "proj" / "other").mkdir()
    (tmp_path / "proj" / "alembic.ini").write_text("[alembic]\nscript_location = %(here)s/other\n")

    cfg = _alembic_config(start)
    script_location = cfg.get_main_option("script_location")
    assert cfg.config_file_name is None
    assert script_location is not None
    assert Path(script_location).resolve() == _migrations_dir().resolve()


def test_checkout_alembic_ini_is_beside_the_package() -> None:
    import sevn.store.db as db
    from sevn.store.db import _find_alembic_ini

    assert _find_alembic_ini(Path(db.__file__)) == (repo_root() / "host" / "alembic.ini").resolve()


async def test_upgrade_without_alembic_ini(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.store import db

    monkeypatch.setattr(db, "_find_alembic_ini", lambda _start: None)
    db_path = tmp_path / "sevn.db"
    await db.upgrade(f"sqlite+aiosqlite:///{db_path}")
    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        isolation = connection.execute("PRAGMA table_info(agents)").fetchall()
    assert "agents" in tables
    assert "isolation" in {row[1] for row in isolation}
