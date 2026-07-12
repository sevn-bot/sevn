#!/usr/bin/env python3
"""Bundled ``github-manager`` skill — repository variables.

Module: sevn.data.bundled_skills.core.github-manager.scripts.cicd_vars
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
    """Run github manager repository variables CLI.

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
    p.add_argument("--action", required=True, choices=("list", "upsert"))
    p.add_argument("--name")
    p.add_argument("--value")
    args = p.parse_args(argv)
    hooks = resolve_github_skill_hooks(workspace_from_env())
    try:
        if args.action == "list":
            payload = asyncio.run(github_manager.list_repo_variables(hooks, repo=args.repo))
        else:
            if not args.name or args.value is None:
                write_error(code="VALIDATION_ERROR", error="--name and --value required for upsert")
                return 1
            payload = asyncio.run(
                github_manager.upsert_repo_variable(
                    hooks,
                    repo=args.repo,
                    variable_name=args.name,
                    value=args.value,
                ),
            )
    except (RuntimeError, ValueError) as exc:
        write_error(code="GITHUB_VARS_FAILED", error=str(exc))
        return 1
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
