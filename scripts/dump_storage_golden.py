"""Dump the head migration schema as a byte-stable SQL fixture.

``specs/03-storage.md`` §10.7 — Golden SQL fixtures: capture the
post-migration ``sqlite3 .dump`` for ``MIGRATION_HEAD_VERSION`` with
volatile ``schema_migrations.applied_at`` timestamps stripped so the
file is reproducible across runs / hosts.

Module: scripts.dump_storage_golden
Depends: argparse, pathlib, sqlite3, subprocess, sys, tempfile

Exports:
    dump_head_schema — produce the stable dump string for a fresh head DB.
    golden_path — canonical fixture path for ``MIGRATION_HEAD_VERSION``.
    main — CLI entry; ``--write`` refreshes the fixture, default prints.

Examples:
    >>> from scripts.dump_storage_golden import dump_head_schema
    >>> "CREATE TABLE schema_migrations" in dump_head_schema()
    True
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from sevn.storage.migrate import MIGRATION_HEAD_VERSION, apply_migrations

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "storage" / "golden"

# ``applied_at`` is the only wallclock value in the dump; everything else
# (DDL + ``sqlite_sequence`` reset) is deterministic for a fresh head DB.
_VOLATILE_SCHEMA_MIGRATIONS_ROW = re.compile(
    r"^INSERT INTO schema_migrations VALUES\((\d+),'[^']*'\);$",
)


def golden_path(head_version: int = MIGRATION_HEAD_VERSION) -> Path:
    """Return the canonical fixture path for ``head_version``.

    Args:
        head_version (int): Migration version captured by the fixture.

    Returns:
        Path: ``tests/fixtures/storage/golden/migration_<NN>.sql``.

    Examples:
        >>> golden_path(14).name
        'migration_14.sql'
    """
    return GOLDEN_DIR / f"migration_{head_version:02d}.sql"


def _stabilise(dump: str) -> str:
    """Strip wallclock-dependent rows from ``sqlite3 .dump`` output.

    The only volatile content is each ``schema_migrations`` insert, whose
    ``applied_at`` defaults to ``datetime('now')``. We replace it with a
    deterministic placeholder so the dump byte-matches across hosts.

    Args:
        dump (str): Raw ``.dump`` output from ``sqlite3``.

    Returns:
        str: Same dump with applied-at timestamps neutralised; newline-terminated.

    Examples:
        >>> _stabilise("INSERT INTO schema_migrations VALUES(1,'2026-01-01 00:00:00');\\n")
        "INSERT INTO schema_migrations VALUES(1,'<applied_at>');\\n"
    """
    out_lines: list[str] = []
    for line in dump.splitlines():
        match = _VOLATILE_SCHEMA_MIGRATIONS_ROW.match(line)
        if match:
            out_lines.append(
                f"INSERT INTO schema_migrations VALUES({match.group(1)},'<applied_at>');",
            )
        else:
            out_lines.append(line)
    return "\n".join(out_lines) + "\n"


def dump_head_schema() -> str:
    """Migrate a fresh SQLite file to head and return its stable ``.dump``.

    Uses a temp file (not ``:memory:``) because ``sqlite3 <db> .dump`` runs
    in a subprocess and needs a path; both produce the same DDL.

    Returns:
        str: Newline-terminated, byte-stable SQL dump of the head schema.

    Examples:
        >>> dump = dump_head_schema()
        >>> dump.startswith("PRAGMA foreign_keys=OFF;\\n")
        True
        >>> dump.rstrip().endswith("COMMIT;")
        True
    """
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "head.db"
        conn = sqlite3.connect(db)
        try:
            apply_migrations(conn)
            conn.commit()
        finally:
            conn.close()
        raw = subprocess.check_output(["sqlite3", str(db), ".dump"], text=True)
    return _stabilise(raw)


def main(argv: list[str] | None = None) -> int:
    """CLI entry: print the dump or write it to the golden fixture.

    Args:
        argv (list[str] | None): Optional argv override for tests.

    Returns:
        int: ``0`` on success.

    Examples:
        >>> main([]) in (0, 1)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Overwrite the golden fixture for MIGRATION_HEAD_VERSION.",
    )
    args = parser.parse_args(argv)

    dump = dump_head_schema()
    target = golden_path()
    if args.write:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(dump, encoding="utf-8")
        print(f"wrote {target.relative_to(REPO_ROOT)} ({MIGRATION_HEAD_VERSION=})")
    else:
        sys.stdout.write(dump)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI smoke
    raise SystemExit(main())
