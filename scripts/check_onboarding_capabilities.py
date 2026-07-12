"""Validate onboarding capability manifest drift (`plan/onboarding-comprehensive-setup` W1.2).

Module: scripts.check_onboarding_capabilities
Depends: json, pathlib, sevn.data.skills_index, sevn.onboarding.capabilities_manifest

Exports:
    main — exit 1 on manifest / schema / INDEX drift.

Examples:
    >>> isinstance(REPO, Path)
    True
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from sevn.data.skills_index import read_skills_index
from sevn.onboarding.capabilities_manifest import load_manifest, skill_capability_id

REPO = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO / "infra" / "sevn.schema.json"
KNOWN_INSTALL_KINDS = {
    "uv_extra",
    "subprocess",
    "make_target",
    "noop",
    "secret_required",
    "second_brain_bootstrap",
}
EXPECTED_GROUPS = {"A", "B", "C", "D", "E", "F", "G"}


def _schema_node_for_path(schema: dict[str, Any], path: str) -> bool:
    """Return whether ``path`` is allowed under ``sevn.schema.json`` root properties.

    Walks declared ``properties`` and treats ``additionalProperties: true`` as accepting
    any child segment.

    Args:
        schema (dict[str, Any]): Parsed ``infra/sevn.schema.json``.
        path (str): Dot path such as ``skills.browser.enabled``.

    Returns:
        bool: True when the path is structurally valid.

    Examples:
        >>> root = {"properties": {"gateway": {"type": "object", "properties": {"port": {}}}}}
        >>> _schema_node_for_path(root, "gateway.port")
        True
    """
    parts = [p for p in path.split(".") if p]
    if not parts:
        return False
    node: dict[str, Any] = schema
    for idx, part in enumerate(parts):
        props = node.get("properties")
        if not isinstance(props, dict):
            return bool(node.get("additionalProperties"))
        if part in props:
            child = props[part]
            if not isinstance(child, dict):
                return False
            if idx == len(parts) - 1:
                return True
            node = child
            continue
        if node.get("additionalProperties") is True:
            return True
        addl = node.get("additionalProperties")
        if isinstance(addl, dict):
            node = addl
            if idx == len(parts) - 1:
                return True
            continue
        return False
    return True


def main() -> int:
    """Run manifest parity checks.

    Returns:
        int: ``0`` when clean; ``1`` on drift.

    Examples:
        >>> main() in (0, 1)
        True
    """
    errors: list[str] = []
    manifest = load_manifest()
    sevn_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    group_ids = {g.id for g in manifest.groups}
    if group_ids != EXPECTED_GROUPS:
        errors.append(f"group ids must be A-G, got {sorted(group_ids)}")

    skill_caps = [c for c in manifest.capabilities if c.capability_id.startswith("skill.")]
    index = read_skills_index()
    expected_skill_ids = {skill_capability_id(name) for name in index}
    actual_skill_ids = {c.capability_id for c in skill_caps}
    missing_skills = sorted(expected_skill_ids - actual_skill_ids)
    extra_skills = sorted(actual_skill_ids - expected_skill_ids)
    if missing_skills:
        errors.append(f"INDEX skills missing from manifest: {', '.join(missing_skills)}")
    if extra_skills:
        errors.append(f"manifest skill rows not in INDEX: {', '.join(extra_skills)}")
    if len(actual_skill_ids) != len(index):
        errors.append(
            f"expected exactly one manifest row per INDEX skill ({len(index)}), got {len(actual_skill_ids)}"
        )

    cap_ids = [c.capability_id for c in manifest.capabilities]
    if len(cap_ids) != len(set(cap_ids)):
        errors.append("duplicate capability_id values in manifest")

    root_schema = sevn_schema.get("properties", {})
    if not isinstance(root_schema, dict):
        errors.append("sevn.schema.json missing root properties")
    else:
        wrapper = {"properties": root_schema, "additionalProperties": False}
        for cap in manifest.capabilities:
            for cfg_path in cap.config_paths:
                if not _schema_node_for_path(wrapper, cfg_path):
                    errors.append(
                        f"{cap.capability_id}: config_paths {cfg_path!r} not in sevn.schema.json"
                    )
            for action in cap.install_actions:
                if action.kind not in KNOWN_INSTALL_KINDS:
                    errors.append(
                        f"{cap.capability_id}: unknown install action kind {action.kind!r}"
                    )

    if errors:
        for line in errors:
            print(f"check_onboarding_capabilities: {line}", file=sys.stderr)
        return 1
    print(
        "check_onboarding_capabilities: ok "
        f"({len(manifest.capabilities)} capabilities, {len(index)} INDEX skills)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
