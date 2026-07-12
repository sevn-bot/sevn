#!/usr/bin/env python3
"""Bundled ``skill_management`` skill — list workspace skill inventory.

Module: sevn.data.bundled_skills.core.skill_management.scripts.list_inventory
Depends: argparse, sevn.lcm.script_cli, sevn.skills.manager

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import workspace_from_env, write_ok
from sevn.skills.manager import SkillsManager


def main() -> int:
    """Run skill inventory list CLI.

    Returns:
        int: ``0`` on success.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--provenance",
        choices=("core", "generated", "user", "plugin"),
        default=None,
    )
    args = parser.parse_args()
    workspace = workspace_from_env()
    manager = SkillsManager.shared(workspace)
    items: list[dict[str, object]] = []
    for skill_id in sorted(manager.index.lines):
        record = manager.get_record(skill_id)
        if args.provenance and record.provenance != args.provenance:
            continue
        items.append(
            {
                "id": skill_id,
                "provenance": record.provenance,
                "version": record.manifest.version,
                "description": record.manifest.description,
                "quarantine": record.quarantine_runtime,
                "script_count": len(record.manifest.scripts),
                "runnable_count": len(record.manifest.runnables),
                "path": str(record.skill_dir),
                "warnings": list(record.validation_errors),
            },
        )
    write_ok({"skills": items, "count": len(items), "registry_version": manager.registry_version})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
