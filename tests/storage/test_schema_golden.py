"""Pin the head migration schema against a checked-in golden ``.dump``.

``specs/03-storage.md`` §10.7 — Golden SQL fixtures: if a migration drifts
the live-DB schema from ``tests/fixtures/storage/golden/migration_<NN>.sql``
this test fails with the path of the regen target so the developer can
intentionally refresh the fixture.
"""

from __future__ import annotations

from pathlib import Path

from scripts.dump_storage_golden import dump_head_schema, golden_path

from sevn.storage.migrate import MIGRATION_HEAD_VERSION

_REFRESH_HINT = (
    "schema drift vs golden fixture {path}.\n"
    "If the migration is intentional, refresh the fixture:\n"
    "    make storage-golden-refresh\n"
    "then commit the updated tests/fixtures/storage/golden/migration_<NN>.sql."
)


def test_golden_fixture_present() -> None:
    """A golden dump exists for ``MIGRATION_HEAD_VERSION``."""
    fixture: Path = golden_path()
    assert fixture.is_file(), (
        f"missing golden fixture for migration {MIGRATION_HEAD_VERSION}: {fixture}\n"
        "Run `make storage-golden-refresh` to create it."
    )


def test_head_schema_matches_golden() -> None:
    """Live head dump must byte-match the checked-in golden fixture."""
    fixture = golden_path()
    expected = fixture.read_text(encoding="utf-8")
    actual = dump_head_schema()
    assert actual == expected, _REFRESH_HINT.format(path=fixture)
