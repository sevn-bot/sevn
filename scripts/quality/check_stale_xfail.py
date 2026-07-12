#!/usr/bin/env python3
"""Fail when tests use stale ``@pytest.mark.xfail`` scaffolding markers.

Module: scripts.quality.check_stale_xfail
Depends: pathlib, re, sys

Exports:
    StaleXfailViolation — one forbidden xfail marker occurrence.
    find_stale_xfail_violations — scan ``tests/`` for forbidden xfail patterns.
    main — CLI entry; exit 1 when violations remain.

Examples:
    >>> find_stale_xfail_violations(Path('tests'))  # doctest: +SKIP
    []
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS_ROOT = REPO / "tests"

_XFAIL_LINE = re.compile(
    r"^\s*@pytest\.mark\.xfail\((?P<body>[^\)]*)\)\s*$",
    re.MULTILINE,
)
_WAVE_REASON = re.compile(r"green after W\d", re.IGNORECASE)


@dataclass(frozen=True)
class StaleXfailViolation:
    """One forbidden xfail marker occurrence."""

    path: Path
    line_no: int
    line: str
    reason: str


def find_stale_xfail_violations(root: Path = TESTS_ROOT) -> list[StaleXfailViolation]:
    """Return xfail markers that hide regressions instead of documenting them.

    Forbidden patterns:
    - ``strict=False`` (XPASS is silent)
    - reasons containing ``green after W*`` (wave scaffolding never removed)

    Args:
        root (Path): Directory tree to scan (defaults to ``tests/``).

    Returns:
        list[StaleXfailViolation]: Sorted violations.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     bad = Path(tmp) / "test_bad.py"
        ...     _ = bad.write_text(
        ...         '@pytest.mark.xfail(reason="green after W5", strict=False)\\n'
        ...         "def test_x(): pass\\n",
        ...         encoding="utf-8",
        ...     )
        ...     hits = find_stale_xfail_violations(Path(tmp))
        ...     len(hits)
        1
    """
    violations: list[StaleXfailViolation] = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in _XFAIL_LINE.finditer(text):
            body = match.group("body")
            line_no = text.count("\n", 0, match.start()) + 1
            line = text.splitlines()[line_no - 1].strip()
            reasons: list[str] = []
            if "strict=False" in body.replace(" ", ""):
                reasons.append("strict=False")
            if _WAVE_REASON.search(body):
                reasons.append("wave scaffolding reason")
            if not reasons:
                continue
            try:
                rel_path = path.relative_to(REPO)
            except ValueError:
                rel_path = path
            violations.append(
                StaleXfailViolation(
                    path=rel_path,
                    line_no=line_no,
                    line=line,
                    reason=", ".join(reasons),
                )
            )
    return violations


def main() -> int:
    """Print violations and exit non-zero when stale xfails remain.

    Returns:
        int: ``0`` when clean; ``1`` when forbidden markers exist.

    Examples:
        >>> main() in (0, 1)
        True
    """
    violations = find_stale_xfail_violations()
    if not violations:
        print("check_stale_xfail: ok (no forbidden xfail markers)")
        return 0
    for item in violations:
        print(
            f"check_stale_xfail: {item.path}:{item.line_no}: {item.reason}: {item.line}",
            file=sys.stderr,
        )
    print(
        f"check_stale_xfail: {len(violations)} forbidden xfail marker(s)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
