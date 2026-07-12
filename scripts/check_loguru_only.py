#!/usr/bin/env python3
"""Guard: application code must use loguru, not stdlib logging (Wave 1 / Wave 6).

Fails when ``src/sevn/**/*.py`` outside the grandfather set imports stdlib
``logging``. Grandfather set is empty after Wave 6; stdlib logging is allowed
only under ``src/sevn/logging/`` (bridge module).

Module: scripts.check_loguru_only
Depends: pathlib, re, sys

Exports:
    main — CLI entry; scans for forbidden stdlib ``logging`` imports.

Examples:
    >>> main() in (0, 1)
    True
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SEVN_SRC = REPO / "src" / "sevn"

_IMPORT_LOGGING = re.compile(r"^\s*(import\s+logging|from\s+logging\b)", re.MULTILINE)

# Empty after Wave 6 — stdlib logging lives only in ``src/sevn/logging/`` bridge code.
_GRANDFATHER_LOGGING: frozenset[str] = frozenset()


def _rel(path: Path) -> str:
    """Return repo-relative posix path for ``path``.

    Args:
        path (Path): Absolute or repo-relative path.

    Returns:
        str: Posix path relative to ``REPO``.

    Examples:
        >>> _rel(REPO / "Makefile")
        'Makefile'
    """
    return path.relative_to(REPO).as_posix()


def main() -> int:
    """Scan ``src/sevn`` for forbidden stdlib ``logging`` imports.

    Returns:
        int: ``0`` when clean, ``1`` when a violation is found.

    Examples:
        >>> main() in (0, 1)
        True
    """
    if not SEVN_SRC.is_dir():
        return 0
    bad: list[str] = []
    for path in sorted(SEVN_SRC.rglob("*.py")):
        rel = _rel(path)
        if rel.startswith("src/sevn/logging/"):
            continue
        if "bundled_skills/core/last30days/" in rel:
            continue
        text = path.read_text(encoding="utf-8")
        if not _IMPORT_LOGGING.search(text):
            continue
        if rel in _GRANDFATHER_LOGGING:
            continue
        bad.append(rel)
    if bad:
        print(
            "loguru-only: stdlib logging import outside grandfather set:\n"
            + "\n".join(f"  {p}" for p in bad),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
