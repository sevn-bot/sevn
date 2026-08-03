"""Migration rehearsal gate for ``sevn.db`` fixture restore + forward migrate.

``specs/03-storage.md`` §10.8 — loads the checked-in golden dump at
``migration_29.sql``, applies pending migrations, and asserts the bundle
head and ``trigger_runs`` schema exist. Invoked by ``make storage-migration-rehearsal-check``.

Module: scripts.check_storage_migration_rehearsal
Depends: pathlib, sqlite3, subprocess, tempfile

Exports:
    run_rehearsal — restore fixture, migrate, assert head + ``trigger_runs``.
    main — CLI entry returning process exit code.

Examples:
    >>> from scripts.check_storage_migration_rehearsal import PRE_MIGRATION_HEAD
    >>> PRE_MIGRATION_HEAD < 30
    True
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from sevn.storage.migrate import MIGRATION_HEAD_VERSION, apply_migrations

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "storage" / "golden"

PRE_MIGRATION_HEAD = MIGRATION_HEAD_VERSION - 1


def _fixture_path(head: int = PRE_MIGRATION_HEAD) -> Path:
    """Return the golden SQL dump path for ``head``.

    Args:
        head (int): Migration version captured by the fixture.

    Returns:
        Path: ``tests/fixtures/storage/golden/migration_<NN>.sql``.

    Examples:
        >>> _fixture_path(29).name
        'migration_29.sql'
    """
    return GOLDEN_DIR / f"migration_{head:02d}.sql"


def run_rehearsal() -> None:
    """Restore the pre-head golden dump, migrate forward, assert schema artifacts.

    Raises:
        AssertionError: When rehearsal preconditions or postconditions fail.
        FileNotFoundError: When the golden fixture is missing.
        subprocess.CalledProcessError: When ``sqlite3`` restore fails.

    Examples:
        >>> run_rehearsal()  # doctest: +SKIP
    """
    fixture = _fixture_path()
    if not fixture.is_file():
        msg = f"missing golden fixture: {fixture}"
        raise FileNotFoundError(msg)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "rehearsal.sqlite"
        subprocess.run(
            ["sqlite3", str(db_path)],
            input=fixture.read_text(encoding="utf-8"),
            text=True,
            check=True,
            capture_output=True,
        )
        conn = sqlite3.connect(db_path)
        try:
            head_before = int(
                conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[
                    0
                ],
            )
            assert head_before == PRE_MIGRATION_HEAD, (
                f"fixture head {head_before} != expected {PRE_MIGRATION_HEAD}"
            )
            apply_migrations(conn)
            head_after = int(
                conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            )
            assert head_after == MIGRATION_HEAD_VERSION, (
                f"migrated head {head_after} != bundle head {MIGRATION_HEAD_VERSION}"
            )
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='trigger_runs'",
            ).fetchone()
            assert row is not None, "trigger_runs table missing after migration"
        finally:
            conn.close()


def main() -> int:
    """Run the migration rehearsal gate.

    Returns:
        int: ``0`` on success, ``1`` on failure.

    Examples:
        >>> main() in (0, 1)
        True
    """
    try:
        run_rehearsal()
    except (AssertionError, FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"storage migration rehearsal failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"storage migration rehearsal ok: "
        f"fixture head {PRE_MIGRATION_HEAD} -> {MIGRATION_HEAD_VERSION}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
