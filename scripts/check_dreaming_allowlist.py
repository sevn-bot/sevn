#!/usr/bin/env python3
"""Static guard: Dreaming must not reference forbidden write targets (`specs/31-memory-dreaming.md` §9).

Fails when ``src/sevn/memory/dreaming/**/*.py`` contains path-shaped references to ``wiki/``,
Honcho ``user_model.json`` store, or ``USER.md`` writes.

Module: scripts.check_dreaming_allowlist
Depends: pathlib, re, sys

Exports:
    main — CLI entry; scans Dreaming sources for forbidden paths.

Examples:
    >>> main() in (0, 1)
    True
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DREAMING = REPO / "src" / "sevn" / "memory" / "dreaming"

FORBIDDEN = (
    re.compile(r"['\"]USER\.md['\"]"),
    re.compile(r"['\"]wiki/"),
    re.compile(r"user_model\.json"),
)


def main() -> int:
    """Scan Dreaming sources for forbidden substrings.

    Returns:
        int: ``0`` when clean, ``1`` when a violation is found.

    Examples:
        >>> main() in (0, 1)
        True
    """
    if not DREAMING.is_dir():
        return 0
    bad: list[str] = []
    for path in sorted(DREAMING.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pat in FORBIDDEN:
            if pat.search(text):
                bad.append(f"{path.relative_to(REPO)} matches {pat.pattern}")
                break
    if bad:
        print("dreaming allowlist: forbidden path references:\n" + "\n".join(bad), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
