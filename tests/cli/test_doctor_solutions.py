"""Doctor solutions catalog tests (W3 — `specs/23-cli.md` §3)."""

from __future__ import annotations

import json
from pathlib import Path

from sevn.cli.doctor.sections import registered_check_ids
from sevn.cli.doctor.solutions import (
    NO_CANNED_SOLUTION,
    load_solutions_catalog,
    lookup_solution,
    solution_for_json,
)

REPO = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO / "src" / "sevn" / "data" / "doctor_solutions.json"


def test_catalog_loads_all_registered_check_ids() -> None:
    catalog = load_solutions_catalog()
    assert registered_check_ids() <= set(catalog.by_id.keys())


def test_operator_lock_solution_is_auto_fixable() -> None:
    row = lookup_solution("operator_lock")
    assert row is not None
    assert row.auto_fixable is True


def test_unknown_check_gets_fallback_json_solution() -> None:
    assert solution_for_json("__no_such_check__")["explanation"] == NO_CANNED_SOLUTION


def test_bundled_json_matches_schema_version() -> None:
    doc = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    assert doc["schema_version"] == 1
