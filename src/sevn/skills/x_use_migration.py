"""Validate operator ``skills/x-use/`` stubs after Playwright skill removal (#128 / D7).

Module: sevn.skills.x_use_migration
Depends: pathlib, sevn.skills.manifest

Exports:
    validate_operator_stub — check a thin alias ``SKILL.md`` points at the social stack.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import yaml

from sevn.skills.errors import SkillExecutionError
from sevn.skills.manifest import manifest_from_mapping, split_frontmatter

TARGET_SKILL: Final[str] = "social_media_manager"

__all__ = ["TARGET_SKILL", "validate_operator_stub"]


def validate_operator_stub(stub_root: Path) -> dict[str, Any]:
    """Validate an operator ``x-use`` stub directory references ``social_media_manager``.

    Accepts a ``SKILL.md`` whose frontmatter ``see_also`` includes ``social_media_manager``
    or whose body mentions ``social_media_manager`` and ``browser action=social``.

    Args:
        stub_root (Path): Operator skill directory (e.g. ``skills/user/x-use``).

    Returns:
        dict[str, Any]: ``{ok, target_skill, reason?}`` validation report.

    Examples:
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp()) / "x-use"
        >>> root.mkdir()
        >>> (root / "SKILL.md").write_text(
        ...     "---\\nname: x-use\\nsee_also:\\n  - social_media_manager\\n---\\n"
        ...     "Use social_media_manager.\\n",
        ...     encoding="utf-8",
        ... )
        >>> validate_operator_stub(root)["ok"]
        True
    """
    skill_md = stub_root / "SKILL.md"
    if not skill_md.is_file():
        return {
            "ok": False,
            "target_skill": TARGET_SKILL,
            "reason": "missing SKILL.md",
        }
    try:
        raw = skill_md.read_text(encoding="utf-8")
        yaml_blob, body = split_frontmatter(raw)
        data = yaml.safe_load(yaml_blob) or {}
        if not isinstance(data, dict):
            msg = "SKILL.md frontmatter must be a mapping"
            raise SkillExecutionError(msg)
        manifest = manifest_from_mapping(
            data,
            body=body,
            provenance="user",
        )
    except (OSError, SkillExecutionError, yaml.YAMLError, ValueError) as exc:
        return {
            "ok": False,
            "target_skill": TARGET_SKILL,
            "reason": str(exc),
        }
    see_also = {item.strip() for item in manifest.see_also if item.strip()}
    body_lower = body.lower()
    points_at_target = TARGET_SKILL in see_also or TARGET_SKILL.replace("_", " ") in body_lower
    mentions_browser_social = "browser action=social" in body_lower or (
        "browser" in body_lower and "social" in body_lower
    )
    if points_at_target and (TARGET_SKILL in see_also or mentions_browser_social):
        return {"ok": True, "target_skill": TARGET_SKILL}
    if points_at_target:
        return {"ok": True, "target_skill": TARGET_SKILL}
    return {
        "ok": False,
        "target_skill": TARGET_SKILL,
        "reason": f"stub must reference {TARGET_SKILL} in see_also or body",
    }
