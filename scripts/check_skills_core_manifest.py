"""Validate bundled core ``SKILL.md`` ↔ ``scripts/*.py`` drift (`specs/12-skills-system.md` §10.5).

Scans ``src/sevn/data/bundled_skills/core/`` (shipped tree mirrored into workspaces).
Exit **1** when a manifest lists a script path with no file, or a ``scripts/*.py``
exists without a matching ``scripts:`` row.

Module: scripts.check_skills_core_manifest
Depends: pathlib, sys, yaml

Exports:
    main — CLI entry; validates bundled core SKILL.md script manifests.

Examples:
    >>> isinstance(REPO, Path)
    True
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CORE_ROOT = REPO / "src" / "sevn" / "data" / "bundled_skills" / "core"


def _load_scripts(skill_dir: Path) -> tuple[list[dict[str, object]], str | None]:
    """Parse ``scripts:`` rows from a skill directory's ``SKILL.md`` frontmatter.

    Args:
        skill_dir (Path): Bundled core skill directory.

    Returns:
        tuple[list[dict[str, object]], str | None]: Script rows and optional error.

    Examples:
        >>> import tempfile
        >>> d = Path(tempfile.mkdtemp())
        >>> _ = (d / "SKILL.md").write_text("---\\nscripts: []\\n---\\n", encoding="utf-8")
        >>> _load_scripts(d)[0]
        []
    """
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        return [], f"missing SKILL.md under {skill_dir.relative_to(REPO)}"
    text = md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return [], f"{md.relative_to(REPO)}: missing YAML frontmatter"
    parts = text.split("---", 2)
    if len(parts) < 3:
        return [], f"{md.relative_to(REPO)}: incomplete frontmatter"
    blob = yaml.safe_load(parts[1]) or {}
    scripts = blob.get("scripts")
    if scripts is None:
        return [], None
    if not isinstance(scripts, list):
        return [], f"{md.relative_to(REPO)}: scripts must be a list"
    rows: list[dict[str, object]] = []
    for row in scripts:
        if isinstance(row, dict):
            rows.append(row)
    return rows, None


def main() -> int:
    """Validate bundled core skill script manifests.

    Returns:
        int: ``0`` when clean, ``1`` on drift or missing tree.

    Examples:
        >>> main() in (0, 1)
        True
    """
    if not CORE_ROOT.is_dir():
        print(f"check_skills_core_manifest: missing tree {CORE_ROOT}", file=sys.stderr)
        return 1
    errors: list[str] = []
    for skill_dir in sorted(CORE_ROOT.iterdir()):
        if not skill_dir.is_dir():
            continue
        rows, err = _load_scripts(skill_dir)
        if err:
            errors.append(err)
            continue
        declared = {str(r.get("path", "")).strip() for r in rows if r.get("path")}
        scripts_dir = skill_dir / "scripts"
        on_disk: set[str] = set()
        if scripts_dir.is_dir():
            for py in scripts_dir.glob("*.py"):
                rel = py.relative_to(skill_dir).as_posix()
                on_disk.add(rel)
        for rel in sorted(declared):
            if not rel:
                continue
            p = skill_dir / rel
            if not p.is_file():
                errors.append(f"{skill_dir.name}: manifest lists missing file `{rel}`")
        for rel in sorted(on_disk):
            if rel not in declared:
                errors.append(
                    f"{skill_dir.name}: file `{rel}` not listed under scripts: in SKILL.md"
                )
    if errors:
        print("check_skills_core_manifest: failures:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
