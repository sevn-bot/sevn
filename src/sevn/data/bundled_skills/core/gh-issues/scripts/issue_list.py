#!/usr/bin/env python3
"""Bundled ``gh-issues`` skill — list issues.

Module: sevn.data.bundled_skills.core.gh-issues.scripts.issue_list
Depends: argparse, asyncio, sevn.integrations.github_skill, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import asyncio

from sevn.integrations.github_skill import gh_issues, resolve_github_skill_hooks
from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok


def main(argv: list[str] | None = None) -> int:
    """Run gh issues list issues CLI.

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
    p.add_argument("--state", default="open", choices=("open", "closed", "all"))
    p.add_argument("--label", action="append", default=[])
    args = p.parse_args(argv)
    hooks = resolve_github_skill_hooks(workspace_from_env())
    try:
        payload = asyncio.run(
            gh_issues.list_issues(
                hooks, repo=args.repo, state=args.state, labels=args.label or None
            )
        )
    except (RuntimeError, ValueError) as exc:
        write_error(code="GITHUB_ISSUE_LIST_FAILED", error=str(exc))
        return 1
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
