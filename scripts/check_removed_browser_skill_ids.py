#!/usr/bin/env python3
"""Static guard: removed Playwright skill trees must not reappear (#117, #127, D6).

Fails when ``src/sevn/data/bundled_skills/`` contains forbidden skill package
directories or removed-id / ``playwright_browser`` substrings, or when
``src/sevn/tools/registry.py`` lists a removed skill id.

Module: scripts.check_removed_browser_skill_ids
Depends: pathlib, sys, scripts.removed_browser_skill_policy

Exports:
    main — CLI entry; scans bundled skills and tools registry for removed ids.

Examples:
    >>> main() in (0, 1)
    True
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.removed_browser_skill_policy import (  # noqa: E402
    FORBIDDEN_SUBSTRINGS,
    MIGRATION_DOC_REL_PATHS,
    REMOVED_SKILL_IDS,
    contains_forbidden_substring,
)

REPO = _REPO
BUNDLED_ROOT = REPO / "src" / "sevn" / "data" / "bundled_skills"
TOOLS_REGISTRY = REPO / "src" / "sevn" / "tools" / "registry.py"

_BINARY_SUFFIXES = frozenset({".pyc", ".png", ".jpg", ".jpeg", ".gif", ".webp"})


def _scan_bundled_tree() -> list[str]:
    """Return human-readable violations under the bundled skills tree.

    Returns:
        list[str]: One line per violation (empty when clean).

    Examples:
        >>> _scan_bundled_tree()  # doctest: +SKIP
        []
    """
    if not BUNDLED_ROOT.is_dir():
        return [f"missing bundled skills tree {BUNDLED_ROOT.relative_to(REPO)}"]

    bad: list[str] = []
    for path in sorted(BUNDLED_ROOT.rglob("*")):
        if path.is_dir() and path.name in REMOVED_SKILL_IDS:
            bad.append(
                f"removed skill directory {path.relative_to(REPO)} (forbidden id {path.name!r})"
            )
            continue
        if not path.is_file() or path.suffix in _BINARY_SUFFIXES:
            continue
        rel = path.relative_to(REPO).as_posix()
        if rel in MIGRATION_DOC_REL_PATHS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for needle in FORBIDDEN_SUBSTRINGS:
            if contains_forbidden_substring(text, needle):
                bad.append(f"{path.relative_to(REPO)}: contains forbidden substring {needle!r}")
                break
    return bad


def _scan_tools_registry() -> list[str]:
    """Return violations when the tools registry lists a removed skill id.

    Returns:
        list[str]: One line per violation (empty when clean).

    Examples:
        >>> isinstance(_scan_tools_registry(), list)
        True
    """
    if not TOOLS_REGISTRY.is_file():
        return []
    text = TOOLS_REGISTRY.read_text(encoding="utf-8")
    bad: list[str] = []
    for skill_id in sorted(REMOVED_SKILL_IDS):
        if contains_forbidden_substring(text, skill_id):
            bad.append(f"{TOOLS_REGISTRY.relative_to(REPO)}: lists removed skill id {skill_id!r}")
    return bad


def main() -> int:
    """Scan bundled skills and tools registry for removed Playwright skill residue.

    Returns:
        int: ``0`` when clean, ``1`` when a violation is found.

    Examples:
        >>> main() in (0, 1)
        True
    """
    bad = _scan_bundled_tree() + _scan_tools_registry()
    if bad:
        print("check_removed_browser_skill_ids: failures:", file=sys.stderr)
        for line in bad:
            print(f"  {line}", file=sys.stderr)
        return 1
    print("check_removed_browser_skill_ids: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
