"""Validate doctor solutions catalog coverage (`plan/cli-comprehensive-parity-doctor` W3.5).

Module: scripts.check_doctor_solutions
Depends: json, pathlib, sevn.cli.doctor.sections, sevn.cli.doctor.solutions

Exports:
    main — exit 1 on schema or coverage drift.

Examples:
    >>> isinstance(REPO, Path)
    True
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sevn.cli.doctor.sections import registered_check_ids
from sevn.cli.doctor.solutions import load_solutions_catalog

REPO = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO / "src" / "sevn" / "data" / "doctor_solutions.json"


def main() -> int:
    """Run registered check-id coverage checks (schema validated by Make target).

    Returns:
        int: ``0`` when clean; ``1`` on drift.

    Examples:
        >>> main() in (0, 1)
        True
    """
    errors: list[str] = []
    if not CATALOG_PATH.is_file():
        errors.append(f"missing catalog: {CATALOG_PATH}")
        for line in errors:
            print(line, file=sys.stderr)
        return 1

    catalog = load_solutions_catalog()
    registered = registered_check_ids()
    catalog_ids = set(catalog.by_id.keys())
    missing = sorted(registered - catalog_ids)
    extra = sorted(catalog_ids - registered)
    if missing:
        errors.append(f"catalog missing entries for registered check ids: {missing}")
    if extra:
        errors.append(f"catalog has unknown check ids (not in doctor registry): {extra}")

    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    solutions = raw.get("solutions", {})
    if isinstance(solutions, dict):
        for check_id, row in solutions.items():
            if not isinstance(row, dict) or row.get("agent_only"):
                continue
            for key in ("title", "severity", "explanation", "remediation", "auto_fixable"):
                if key not in row:
                    errors.append(f"{check_id}: missing required field {key!r}")

    if errors:
        for line in errors:
            print(line, file=sys.stderr)
        return 1
    print(
        f"doctor solutions catalog ok ({len(catalog_ids)} entries, {len(registered)} registered ids)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
