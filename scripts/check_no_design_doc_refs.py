#!/usr/bin/env python3
"""Reject references to the gitignored design-doc trees in published surfaces.

The ``plan/``, ``specs/``, and ``prd/`` directories are local-only (gitignored), so
citing their paths in public docs or schemas leaves dangling references for anyone
who clones the repo. This hook forbids such citations.

It is intentionally scoped (via ``.pre-commit-config.yaml`` ``files:``) to published,
non-code surfaces — ``README.md``, ``CHANGELOG.md``, ``about-sevn.bot/``, and the JSON
schema/template/description files. Python docstrings legitimately cite ADRs per the
coding standard and are NOT checked here.

Module: scripts.check_no_design_doc_refs
Depends: argparse, re, sys, pathlib

Exports:
    find_violations - return offending ``(lineno, line)`` pairs for one file.
    main - scan the given files and exit non-zero on any forbidden reference.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

# A path-like reference to one of the design-doc trees, not preceded by a word
# char, dot, dash, or slash — so ``src/sevn/prompts/`` and ``mealplan/`` do not match.
_FORBIDDEN = re.compile(r"(?<![\w./-])(plan|specs|prd)/")


def find_violations(path: Path) -> list[tuple[int, str]]:
    """Return ``(lineno, stripped_line)`` for each line citing a design-doc tree.

    Args:
        path (Path): File to scan.

    Returns:
        list[tuple[int, str]]: One entry per offending line (1-indexed); empty when
            the file is clean or cannot be read as UTF-8 text.

    Examples:
        >>> import pathlib, tempfile
        >>> p = pathlib.Path(tempfile.mkstemp(suffix=".md")[1])
        >>> _ = p.write_text("see s" + "pecs/17.md\\nfine\\n", encoding="utf-8")
        >>> find_violations(p)[0][0]
        1
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return [
        (i, line.strip())
        for i, line in enumerate(text.splitlines(), start=1)
        if _FORBIDDEN.search(line)
    ]


def main(argv: list[str] | None = None) -> int:
    """Scan files passed by pre-commit; exit 1 listing any design-doc references.

    Args:
        argv (list[str] | None): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: 0 when all files are clean, 1 when any forbidden reference is found.

    Examples:
        >>> main([])
        0
    """
    parser = argparse.ArgumentParser(description="Reject design-doc tree references.")
    parser.add_argument("files", nargs="*", help="Files to scan.")
    args = parser.parse_args(argv)

    failed = False
    for name in args.files:
        for lineno, line in find_violations(Path(name)):
            failed = True
            print(f"{name}:{lineno}: cites a gitignored design-doc tree: {line}")
    if failed:
        print(
            "\nplan/, specs/, prd/ are gitignored (local-only); do not cite their "
            "paths in published surfaces. Reword to a generic phrase (e.g. 'the design "
            "docs') or link an about-sevn.bot/ page instead.",
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
