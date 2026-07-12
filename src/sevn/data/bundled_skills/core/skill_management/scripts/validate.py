#!/usr/bin/env python3
"""Bundled ``skill_management`` skill — validate one skill manifest.

Module: sevn.data.bundled_skills.core.skill_management.scripts.validate
Depends: argparse, sevn.lcm.script_cli, sevn.skills.errors, sevn.skills.manager, sevn.skills.manifest

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok
from sevn.skills.errors import SkillExecutionError
from sevn.skills.manager import SkillsManager
from sevn.skills.manifest import validate_script_paths


def main() -> int:
    """Run skill validation CLI.

    Returns:
        int: ``0`` on success; ``1`` when validation fails.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-name", required=True)
    args = parser.parse_args()
    workspace = workspace_from_env()
    manager = SkillsManager.shared(workspace)
    try:
        record = manager.get_record(args.skill_name.strip())
        validate_script_paths(record.skill_dir, record.manifest)
    except SkillExecutionError as exc:
        write_error(code=exc.code, error=str(exc))
        return 1
    write_ok(
        {
            "valid": True,
            "skill_name": record.canonical_id,
            "provenance": record.provenance,
            "quarantine": record.quarantine_runtime,
            "path": str(record.skill_dir),
            "warnings": list(record.validation_errors),
            "script_count": len(record.manifest.scripts),
            "runnable_count": len(record.manifest.runnables),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
