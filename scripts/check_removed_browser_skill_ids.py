#!/usr/bin/env python3
"""Static guard: removed Playwright skill trees must not reappear (#117, #127, D6).

Fails when ``src/sevn/data/bundled_skills/`` contains forbidden skill package
directories or ``playwright-browser`` / ``playwright_browser`` substrings, or when
``src/sevn/tools/registry.py`` lists a removed skill id.

Module: scripts.check_removed_browser_skill_ids
Depends: pathlib, sys

Exports:
    main — CLI entry; scans bundled skills and tools registry for removed ids.

Examples:
    >>> main() in (0, 1)
    True
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BUNDLED_ROOT = REPO / "src" / "sevn" / "data" / "bundled_skills"
TOOLS_REGISTRY = REPO / "src" / "sevn" / "tools" / "registry.py"

REMOVED_SKILL_IDS = frozenset(
    {
        "playwright-browser",
        "x-use",
        "facebook-use",
        "linkedin-use",
    }
)

FORBIDDEN_SUBSTRINGS = (
    "playwright-browser",
    "playwright_browser",
)


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
    for core_root in (BUNDLED_ROOT / "core", BUNDLED_ROOT):
        if not core_root.is_dir():
            continue
        for child in sorted(core_root.iterdir()):
            if child.is_dir() and child.name in REMOVED_SKILL_IDS:
                bad.append(
                    f"removed skill directory {child.relative_to(REPO)} "
                    f"(forbidden id {child.name!r})"
                )

    for path in sorted(BUNDLED_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for needle in FORBIDDEN_SUBSTRINGS:
            if needle in text:
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
        if skill_id in text:
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
