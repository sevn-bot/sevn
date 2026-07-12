"""``capabilities[]`` rows for ``load_skill`` payloads (``specs/12-skills-system.md`` §2.3).

Module: sevn.skills.capabilities
Depends: sevn.skills.manifest

Exports:
    build_skill_capability_rows — map manifest surfaces to envelope rows.

Examples:
    >>> from sevn.skills.manifest import SkillManifest
    >>> m = SkillManifest(name="x", description="y", version="1.0.0")
    >>> build_skill_capability_rows(m)
    []
"""

from __future__ import annotations

from typing import Any

from sevn.skills.manifest import SkillManifest, infer_abortable_for_script


def build_skill_capability_rows(manifest: SkillManifest) -> list[dict[str, Any]]:
    """Return non-empty surfaces for ``load_skill`` when scripts/runnables exist.

    Args:
        manifest (SkillManifest): Parsed authoring contract.

    Returns:
        list[dict[str, Any]]: JSON-serializable ``capabilities[]`` slice.

    Examples:
        >>> from sevn.skills.manifest import SkillScriptEntry, SkillManifest
        >>> mn = SkillManifest(
        ...     name="z",
        ...     description="d",
        ...     version="1.0.0",
        ...     scripts=(SkillScriptEntry(path="scripts/foo.py", description="runs foo"),),
        ... )
        >>> rows = build_skill_capability_rows(mn)
        >>> rows[0]["type"]
        'script'
    """
    rows: list[dict[str, Any]] = []
    for s in manifest.scripts:
        rows.append(
            {
                "type": "script",
                "path": s.path,
                "summary": s.description,
                "args_overview": s.args_overview,
                "abortable": infer_abortable_for_script(s.path, s.abortable),
            }
        )
    for r in manifest.runnables:
        rows.append(
            {
                "type": "runnable",
                "id": r.runnable_id,
                "summary": r.description,
                "parameters": list(r.parameters),
                "abortable": bool(r.abortable) if isinstance(r.abortable, bool) else True,
                "language": r.language,
            }
        )
    return rows
