#!/usr/bin/env python3
"""Bundled ``gh-issues`` skill — maintain the watched-issue set.

Thin CLI over :mod:`sevn.integrations.github_skill.watch`.
"""

from __future__ import annotations

import argparse

from sevn.config.my_sevn import resolve_github_repo_slug
from sevn.integrations.github_skill.watch import load_tracked, save_tracked, tracked_path
from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok

__all__ = ["load_tracked", "main", "save_tracked", "tracked_path"]


def main(argv: list[str] | None = None) -> int:
    """Run gh-issues track CLI (``--add`` / ``--remove`` / ``--list``).

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
    action = p.add_mutually_exclusive_group(required=True)
    action.add_argument("--add", type=int, metavar="N", help="track issue number N")
    action.add_argument("--remove", type=int, metavar="N", help="untrack issue number N")
    action.add_argument("--list", action="store_true", help="list tracked issues")
    p.add_argument("--repo", default=None, help="owner/repo (default: my_sevn.repo_url)")
    args = p.parse_args(argv)
    workspace = workspace_from_env()

    try:
        issues = load_tracked(workspace)
        if args.list:
            write_ok({"issues": issues, "count": len(issues)})
            return 0
        repo = resolve_github_repo_slug(args.repo, workspace=workspace)
        number = int(args.add if args.add is not None else args.remove)
        if args.add is not None:
            if not any(i["repo"] == repo and i["number"] == number for i in issues):
                issues.append({"repo": repo, "number": number})
            path = save_tracked(workspace, issues)
            write_ok(
                {
                    "action": "add",
                    "repo": repo,
                    "number": number,
                    "path": str(path),
                    "issues": issues,
                }
            )
            return 0
        issues = [i for i in issues if not (i["repo"] == repo and i["number"] == number)]
        path = save_tracked(workspace, issues)
        write_ok(
            {
                "action": "remove",
                "repo": repo,
                "number": number,
                "path": str(path),
                "issues": issues,
            }
        )
        return 0
    except (OSError, ValueError) as exc:
        write_error(code="GITHUB_ISSUE_TRACK_FAILED", error=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
