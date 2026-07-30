"""W17.1 - Batch D migration contract (D13).

Green at head 24 before W18 touches storage; future versions 25-29 are xfail until
their implementation waves land and refresh golden fixtures.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from scripts.dump_storage_golden import dump_head_schema, golden_path

from sevn.storage.migrate import MIGRATION_HEAD_VERSION, MIGRATIONS, apply_migrations
from tests.open_issues_sweep.batch_d.conftest import (
    BATCH_D_BASELINE_HEAD,
    BATCH_D_FIRST_IMPL_VERSION,
    BATCH_D_LAST_IMPL_VERSION,
    BATCH_D_MIGRATION_SLOTS,
    table_columns,
    table_exists,
)


def test_batch_d_baseline_head_is_24_before_w18() -> None:
    """W17 gate recorded pre-W18 head 24; W18 advances head to migration 25."""
    assert MIGRATION_HEAD_VERSION >= BATCH_D_BASELINE_HEAD
    registered = {version for version, _ in MIGRATIONS}
    assert 25 in registered


def test_migration_head_matches_migrations_tail() -> None:
    """``MIGRATION_HEAD_VERSION`` must equal the last ``MIGRATIONS`` entry."""
    tail_version = MIGRATIONS[-1][0]
    assert tail_version == MIGRATION_HEAD_VERSION


def test_batch_d_planned_versions_are_contiguous_25_through_29() -> None:
    """W0.8 assigns migrations 25→W18 … 29→W22 without gaps."""
    versions = [slot.version for slot in BATCH_D_MIGRATION_SLOTS]
    assert versions == list(range(BATCH_D_FIRST_IMPL_VERSION, BATCH_D_LAST_IMPL_VERSION + 1))
    waves = [slot.wave for slot in BATCH_D_MIGRATION_SLOTS]
    assert waves == ["W18", "W19", "W20", "W21", "W22"]


def test_batch_d_all_planned_migrations_registered() -> None:
    """Batch D migrations 25-29 are registered after W22."""
    registered = {version for version, _ in MIGRATIONS}
    for slot in BATCH_D_MIGRATION_SLOTS:
        assert slot.version in registered


def test_batch_d_migration_26_registered() -> None:
    """W19 registers migration 26 for durable subagent result bodies."""
    registered = {version for version, _ in MIGRATIONS}
    assert 26 in registered


def test_batch_d_migration_27_registered() -> None:
    """W20 registers migration 27 for subagent transcript paths."""
    registered = {version for version, _ in MIGRATIONS}
    assert 27 in registered


def test_batch_d_migration_28_registered() -> None:
    """W21 registers migration 28 for cron execution audit history."""
    registered = {version for version, _ in MIGRATIONS}
    assert 28 in registered


def test_batch_d_migration_29_registered() -> None:
    """W22 registers migration 29 for session export audit metadata."""
    registered = {version for version, _ in MIGRATIONS}
    assert 29 in registered


def test_apply_migrations_idempotent_at_batch_d_baseline(tmp_path: Path) -> None:
    """Every bundled migration through current head applies idempotently."""
    db_path = tmp_path / "idempotent.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        apply_migrations(conn)
        apply_migrations(conn)
        ver = int(conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0])
        assert ver == MIGRATION_HEAD_VERSION
    finally:
        conn.close()


def test_golden_fixture_present_for_batch_d_baseline() -> None:
    """Golden dump exists for the pre-implementation head."""
    fixture = golden_path(BATCH_D_BASELINE_HEAD)
    assert fixture.is_file(), f"missing golden fixture: {fixture}"


def test_head_schema_matches_golden_at_batch_d_baseline() -> None:
    """Live head dump byte-matches the checked-in golden fixture for migration 25."""
    fixture = golden_path(MIGRATION_HEAD_VERSION)
    expected = fixture.read_text(encoding="utf-8")
    actual = dump_head_schema()
    assert actual == expected


@pytest.mark.parametrize(
    "slot",
    [s for s in BATCH_D_MIGRATION_SLOTS if s.version > 29],
    ids=[f"v{s.version}_{s.wave}" for s in BATCH_D_MIGRATION_SLOTS if s.version > 29],
)
@pytest.mark.xfail(reason="green after impl wave: migration registered", strict=False)
def test_batch_d_migration_registered(slot: object) -> None:
    """Each planned migration version appears in ``MIGRATIONS``."""
    from tests.open_issues_sweep.batch_d.conftest import BatchDMigrationSlot

    assert isinstance(slot, BatchDMigrationSlot)
    registered = {version for version, _ in MIGRATIONS}
    assert slot.version in registered


def test_batch_d_migration_25_registered() -> None:
    """W18 registers migration 25 for the delivery-obligation ledger."""
    registered = {version for version, _ in MIGRATIONS}
    assert 25 in registered


@pytest.mark.parametrize(
    "slot",
    [s for s in BATCH_D_MIGRATION_SLOTS if s.version > 29],
    ids=[f"v{s.version}_{s.wave}" for s in BATCH_D_MIGRATION_SLOTS if s.version > 29],
)
@pytest.mark.xfail(reason="green after impl wave: schema artifact present", strict=False)
def test_batch_d_migration_schema_artifact(slot: object, tmp_path: Path) -> None:
    """Each wave's table/column contract exists after ``apply_migrations``."""
    from tests.open_issues_sweep.batch_d.conftest import BatchDMigrationSlot

    assert isinstance(slot, BatchDMigrationSlot)
    conn = sqlite3.connect(tmp_path / f"m{slot.version}.sqlite")
    try:
        apply_migrations(conn)
        if slot.table is not None:
            assert table_exists(conn, slot.table), f"missing table {slot.table!r}"
            cols = table_columns(conn, slot.table)
            for col_name, col_type in slot.columns:
                assert col_name in cols, f"missing column {col_name!r} on {slot.table!r}"
                assert cols[col_name].upper() == col_type.upper()
    finally:
        conn.close()


def test_batch_d_migration_25_schema_artifact(tmp_path: Path) -> None:
    """W18 ``delivery_obligations`` table exists after ``apply_migrations``."""
    slot = next(s for s in BATCH_D_MIGRATION_SLOTS if s.version == 25)
    conn = sqlite3.connect(tmp_path / "m25.sqlite")
    try:
        apply_migrations(conn)
        assert slot.table is not None
        assert table_exists(conn, slot.table), f"missing table {slot.table!r}"
    finally:
        conn.close()


def test_batch_d_migration_26_schema_artifact(tmp_path: Path) -> None:
    """W19 ``subagent_runs.result_body`` column exists after ``apply_migrations``."""
    slot = next(s for s in BATCH_D_MIGRATION_SLOTS if s.version == 26)
    conn = sqlite3.connect(tmp_path / "m26.sqlite")
    try:
        apply_migrations(conn)
        assert slot.table is not None
        assert table_exists(conn, slot.table), f"missing table {slot.table!r}"
        cols = table_columns(conn, slot.table)
        for col_name, col_type in slot.columns:
            assert col_name in cols, f"missing column {col_name!r} on {slot.table!r}"
            assert cols[col_name].upper() == col_type.upper()
    finally:
        conn.close()


def test_batch_d_migration_27_schema_artifact(tmp_path: Path) -> None:
    """W20 ``subagent_runs.transcript_path`` column exists after ``apply_migrations``."""
    slot = next(s for s in BATCH_D_MIGRATION_SLOTS if s.version == 27)
    conn = sqlite3.connect(tmp_path / "m27.sqlite")
    try:
        apply_migrations(conn)
        assert slot.table is not None
        assert table_exists(conn, slot.table), f"missing table {slot.table!r}"
        cols = table_columns(conn, slot.table)
        for col_name, col_type in slot.columns:
            assert col_name in cols, f"missing column {col_name!r} on {slot.table!r}"
            assert cols[col_name].upper() == col_type.upper()
    finally:
        conn.close()


def test_batch_d_migration_28_schema_artifact(tmp_path: Path) -> None:
    """W21 ``cron_runs`` table exists after ``apply_migrations``."""
    slot = next(s for s in BATCH_D_MIGRATION_SLOTS if s.version == 28)
    conn = sqlite3.connect(tmp_path / "m28.sqlite")
    try:
        apply_migrations(conn)
        assert slot.table is not None
        assert table_exists(conn, slot.table), f"missing table {slot.table!r}"
        cols = set(table_columns(conn, slot.table))
        assert cols >= {
            "job_id",
            "run_id",
            "claimed_at",
            "completed_at",
            "status",
            "transcript_path",
            "result_summary",
            "error",
        }
    finally:
        conn.close()


def test_batch_d_migration_29_schema_artifact(tmp_path: Path) -> None:
    """W22 ``session_export_jobs`` table exists after ``apply_migrations``."""
    slot = next(s for s in BATCH_D_MIGRATION_SLOTS if s.version == 29)
    conn = sqlite3.connect(tmp_path / "m29.sqlite")
    try:
        apply_migrations(conn)
        assert slot.table is not None
        assert table_exists(conn, slot.table), f"missing table {slot.table!r}"
    finally:
        conn.close()


@pytest.mark.parametrize(
    "slot",
    [s for s in BATCH_D_MIGRATION_SLOTS if s.version > 29],
    ids=[f"v{s.version}_{s.wave}" for s in BATCH_D_MIGRATION_SLOTS if s.version > 29],
)
@pytest.mark.xfail(reason="green after impl wave: golden fixture refreshed", strict=False)
def test_batch_d_golden_fixture_for_version(slot: object) -> None:
    """Each new migration version has a checked-in golden SQL dump."""
    from tests.open_issues_sweep.batch_d.conftest import BatchDMigrationSlot

    assert isinstance(slot, BatchDMigrationSlot)
    fixture = golden_path(slot.version)
    assert fixture.is_file(), f"missing golden fixture for migration {slot.version}: {fixture}"


def test_batch_d_golden_fixture_for_migration_25() -> None:
    """W18 golden dump exists for migration 25."""
    fixture = golden_path(25)
    assert fixture.is_file(), f"missing golden fixture for migration 25: {fixture}"


def test_batch_d_golden_fixture_for_migration_26() -> None:
    """W19 golden dump exists for migration 26."""
    fixture = golden_path(26)
    assert fixture.is_file(), f"missing golden fixture for migration 26: {fixture}"


def test_batch_d_golden_fixture_for_migration_27() -> None:
    """W20 golden dump exists for migration head 27."""
    fixture = golden_path(27)
    assert fixture.is_file(), f"missing golden fixture for migration 27: {fixture}"


def test_batch_d_golden_fixture_for_migration_28() -> None:
    """W21 golden dump exists for migration head 28."""
    fixture = golden_path(28)
    assert fixture.is_file(), f"missing golden fixture for migration 28: {fixture}"


def test_batch_d_golden_fixture_for_migration_29() -> None:
    """W22 golden dump exists for migration head 29."""
    fixture = golden_path(29)
    assert fixture.is_file(), f"missing golden fixture for migration 29: {fixture}"
