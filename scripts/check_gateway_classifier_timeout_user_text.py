#!/usr/bin/env python3
"""Forbid user-facing classifier-timeout copy under ``src/sevn/gateway/`` (#119, D5).

Batch A #70 removed ``notify_operator`` on classifier-fallback spawn; this gate
prevents reintroducing Telegram-visible timeout notices. Runtime behaviour is
also covered by ``tests/gateway/test_classifier_timeout.py`` and
``tests/gateway/test_queue_multi.py``.

Module: scripts.check_gateway_classifier_timeout_user_text
Depends: pathlib, re, sys

Exports:
    find_violations — return offending ``(relpath, detail)`` pairs for one file.
    main — scan gateway Python sources and exit non-zero on forbidden text.

Examples:
    >>> main() in (0, 1)
    True
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GATEWAY_SRC = REPO / "src" / "sevn" / "gateway"

_FORBIDDEN_LITERALS: tuple[str, ...] = (
    "Queue classifier timed out",
    "queuing this message as its own turn",
    "classifier timed out — queuing",
)

_FORBIDDEN_REGEX = re.compile(
    r"classifier\s+timed\s+out.*(?:queu|own\s+turn)",
    re.IGNORECASE,
)


def find_violations(path: Path) -> list[tuple[str, str]]:
    """Return ``(relpath, detail)`` for each forbidden classifier-timeout string.

    Args:
        path (Path): Gateway Python source file to scan.

    Returns:
        list[tuple[str, str]]: Violations; empty when the file is clean.

    Examples:
        >>> import tempfile
        >>> p = Path(tempfile.mkstemp(suffix=".py")[1])
        >>> _ = p.write_text('msg = "Queue classifier timed out"\\n', encoding="utf-8")
        >>> find_violations(p)[0][1]
        'literal Queue classifier timed out'
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    rel = path.relative_to(REPO).as_posix()
    hits: list[tuple[str, str]] = []
    for needle in _FORBIDDEN_LITERALS:
        if needle in text:
            hits.append((rel, f"literal {needle!r}"))
    for match in _FORBIDDEN_REGEX.finditer(text):
        hits.append((rel, f"regex {match.group(0)!r}"))
    return hits


def main() -> int:
    """Scan ``src/sevn/gateway/**/*.py`` for forbidden user-facing timeout copy.

    Returns:
        int: ``0`` when clean, ``1`` when any violation is found.

    Examples:
        >>> main() in (0, 1)
        True
    """
    if not GATEWAY_SRC.is_dir():
        return 0
    violations: list[tuple[str, str]] = []
    for path in sorted(GATEWAY_SRC.rglob("*.py")):
        violations.extend(find_violations(path))
    if not violations:
        return 0
    print(
        "gateway-classifier-timeout-user-text: forbidden strings under src/sevn/gateway/:\n"
        + "\n".join(f"  {rel}: {detail}" for rel, detail in violations),
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
