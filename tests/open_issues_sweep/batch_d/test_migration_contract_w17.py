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
    """W17 gate: implementation starts from migration head 24."""
    assert MIGRATION_HEAD_VERSION == BATCH_D_BASELINE_HEAD


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


def test_batch_d_no_impl_migrations_registered_yet() -> None:
    """Head must remain 24 until W18 appends migration 25."""
    registered = {version for version, _ in MIGRATIONS}
    for slot in BATCH_D_MIGRATION_SLOTS:
        assert slot.version not in registered


def test_apply_migrations_idempotent_at_batch_d_baseline(tmp_path: Path) -> None:
    """Every bundled migration through head 24 applies idempotently."""
    db_path = tmp_path / "idempotent.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        apply_migrations(conn)
        apply_migrations(conn)
        ver = int(conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0])
        assert ver == BATCH_D_BASELINE_HEAD
    finally:
        conn.close()


def test_golden_fixture_present_for_batch_d_baseline() -> None:
    """Golden dump exists for the pre-implementation head."""
    fixture = golden_path(BATCH_D_BASELINE_HEAD)
    assert fixture.is_file(), f"missing golden fixture: {fixture}"


def test_head_schema_matches_golden_at_batch_d_baseline() -> None:
    """Live head dump byte-matches the checked-in golden fixture."""
    fixture = golden_path(BATCH_D_BASELINE_HEAD)
    expected = fixture.read_text(encoding="utf-8")
    actual = dump_head_schema()
    assert actual == expected


@pytest.mark.parametrize(
    "slot",
    BATCH_D_MIGRATION_SLOTS,
    ids=[f"v{s.version}_{s.wave}" for s in BATCH_D_MIGRATION_SLOTS],
)
@pytest.mark.xfail(reason="green after impl wave: migration registered", strict=False)
def test_batch_d_migration_registered(slot: object) -> None:
    """Each planned migration version appears in ``MIGRATIONS``."""
    from tests.open_issues_sweep.batch_d.conftest import BatchDMigrationSlot

    assert isinstance(slot, BatchDMigrationSlot)
    registered = {version for version, _ in MIGRATIONS}
    assert slot.version in registered


@pytest.mark.parametrize(
    "slot",
    BATCH_D_MIGRATION_SLOTS,
    ids=[f"v{s.version}_{s.wave}" for s in BATCH_D_MIGRATION_SLOTS],
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


@pytest.mark.parametrize(
    "slot",
    BATCH_D_MIGRATION_SLOTS,
    ids=[f"v{s.version}_{s.wave}" for s in BATCH_D_MIGRATION_SLOTS],
)
@pytest.mark.xfail(reason="green after impl wave: golden fixture refreshed", strict=False)
def test_batch_d_golden_fixture_for_version(slot: object) -> None:
    """Each new migration version has a checked-in golden SQL dump."""
    from tests.open_issues_sweep.batch_d.conftest import BatchDMigrationSlot

    assert isinstance(slot, BatchDMigrationSlot)
    fixture = golden_path(slot.version)
    assert fixture.is_file(), f"missing golden fixture for migration {slot.version}: {fixture}"
