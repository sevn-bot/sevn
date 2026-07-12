"""Validate ``src/sevn/data/skills/INDEX.md`` against shipped ``bundled_skills/core/*``.

Module: scripts.check_skills_index
Depends: pathlib, sys, sevn.data.skills_index, yaml.

Bidirectional drift check (``PROBLEMS.md`` §Priority 1.b):

- every ``src/sevn/data/bundled_skills/core/<name>/SKILL.md`` has a row in
  ``src/sevn/data/skills/INDEX.md``
- every row in the packaged index resolves to a ``bundled_skills/core/<name>/``
  directory

Run via ``uv run python scripts/check_skills_index.py`` or the
``sevn-skills-index`` pre-commit hook. Exits ``1`` on any drift.

Exports:
    main — CLI entry; returns ``0`` clean, ``1`` on drift.

Examples:
    >>> isinstance(REPO, Path)
    True
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from sevn.data.skills_index import _parse_table

REPO = Path(__file__).resolve().parents[1]
CORE_ROOT = REPO / "src" / "sevn" / "data" / "bundled_skills" / "core"
INDEX_PATH = REPO / "src" / "sevn" / "data" / "skills" / "INDEX.md"


def _shipped_skill_names() -> set[str]:
    """Return the set of bundled core skill names taken from ``SKILL.md`` frontmatter.

    Falls back to the directory name when the frontmatter omits ``name``.

    Returns:
        set[str]: Canonical skill identifiers shipped under ``bundled_skills/core/``.

    Examples:
        >>> CORE_ROOT.is_dir()
        True
    """
    names: set[str] = set()
    for d in sorted(CORE_ROOT.iterdir()):
        if not d.is_dir():
            continue
        md = d / "SKILL.md"
        if not md.is_file():
            continue
        text = md.read_text(encoding="utf-8")
        name: str = d.name
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                fm = yaml.safe_load(parts[1]) or {}
                raw = fm.get("name")
                if isinstance(raw, str) and raw.strip():
                    name = raw.strip()
        names.add(name)
    return names


def main() -> int:
    """Run the index/bundled drift check.

    Returns:
        int: ``0`` when in sync, ``1`` on any drift or missing tree.

    Examples:
        >>> main() in (0, 1)
        True
    """
    if not CORE_ROOT.is_dir():
        print(
            f"check_skills_index: missing bundled tree {CORE_ROOT}",
            file=sys.stderr,
        )
        return 1
    if not INDEX_PATH.is_file():
        print(
            f"check_skills_index: missing {INDEX_PATH.relative_to(REPO)}; "
            f"see PROBLEMS.md §Priority 1.a",
            file=sys.stderr,
        )
        return 1

    shipped = _shipped_skill_names()
    indexed = set(_parse_table(INDEX_PATH.read_text(encoding="utf-8")).keys())

    errors: list[str] = []
    for name in sorted(shipped - indexed):
        errors.append(
            f"  shipped skill `{name}` (bundled_skills/core/{name}/) has no row in "
            f"{INDEX_PATH.relative_to(REPO)}"
        )
    for name in sorted(indexed - shipped):
        errors.append(
            f"  {INDEX_PATH.relative_to(REPO)} row `{name}` has no matching "
            f"bundled_skills/core/{name}/ directory"
        )

    if errors:
        print("skills INDEX drift:", file=sys.stderr)
        for line in errors:
            print(line, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
