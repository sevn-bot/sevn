#!/usr/bin/env python3
"""Bundled ``github-manager`` skill — dispatch workflow.

Module: sevn.data.bundled_skills.core.github-manager.scripts.actions_run
Depends: argparse, asyncio, sevn.integrations.github_skill, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import asyncio

from sevn.integrations.github_skill import github_manager, resolve_github_skill_hooks
from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok


def main(argv: list[str] | None = None) -> int:
    """Run github manager dispatch workflow CLI.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("repo")
    p.add_argument("--workflow-id", required=True)
    p.add_argument("--ref", required=True)
    p.add_argument("--input", action="append", default=[], help="KEY=VAL workflow input")
    args = p.parse_args(argv)
    inputs: dict[str, str] = {}
    for item in args.input:
        if "=" in item:
            key, val = item.split("=", 1)
            inputs[key] = val
    hooks = resolve_github_skill_hooks(workspace_from_env())
    try:
        payload = asyncio.run(
            github_manager.dispatch_workflow(
                hooks,
                repo=args.repo,
                workflow_id=args.workflow_id,
                ref=args.ref,
                inputs=inputs or None,
            ),
        )
    except (RuntimeError, ValueError) as exc:
        write_error(code="GITHUB_ACTIONS_RUN_FAILED", error=str(exc))
        return 1
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
