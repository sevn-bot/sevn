#!/usr/bin/env python3
"""Bundled ``skill_management`` skill — authoring workflow guide.

Module: sevn.data.bundled_skills.core.skill_management.scripts.authoring_workflow
Depends: argparse, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import write_ok


def _workflow(*, skill_name: str | None) -> dict[str, object]:
    """Return structured authoring steps referencing native tools.

    Args:
        skill_name (str | None): Optional example skill basename.

    Returns:
        dict[str, object]: Workflow payload for the agent.

    Examples:
        >>> steps = _workflow(skill_name="demo")["steps"]
        >>> isinstance(steps, list) and steps[0]["tool"] == "skill_create"
        True
    """
    example = skill_name or "<name>"
    return {
        "summary": (
            "Scaffold with native skill_create, iterate via run_skill_script, "
            "then promote_generated_skill after human review."
        ),
        "native_tools": {
            "skill_create": {
                "purpose": "Create workspace/skills/generated/<name>/ with quarantine: true",
                "example_arguments": {
                    "name": example,
                    "description": "One-line Triager description",
                    "create_scripts_dir": True,
                },
            },
            "promote_generated_skill": {
                "purpose": "Move generated/<name>/ to user/<name>/ and clear quarantine",
                "requires_human": True,
                "example_arguments": {"name": example},
            },
        },
        "steps": [
            {
                "order": 1,
                "tool": "skill_create",
                "detail": f"Scaffold generated/{example}/ with SKILL.md and scripts/ directory.",
            },
            {
                "order": 2,
                "tool": "run_skill_script",
                "detail": "Add scripts/*.py, list them under scripts: in SKILL.md, and smoke-test each script.",
            },
            {
                "order": 3,
                "skill_script": "validate.py",
                "detail": "Run bundled validate.py --skill-name before promotion.",
            },
            {
                "order": 4,
                "tool": "promote_generated_skill",
                "detail": "Promote stable generated skills into workspace/skills/user/ after operator ack.",
            },
        ],
        "spec_refs": [
            "specs/12-skills-system.md §2.5",
            "specs/11-tools-registry.md §3.4",
        ],
    }


def main() -> int:
    """Run authoring workflow guide CLI.

    Returns:
        int: ``0`` on success.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-name", default=None)
    args = parser.parse_args()
    write_ok(_workflow(skill_name=args.skill_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
