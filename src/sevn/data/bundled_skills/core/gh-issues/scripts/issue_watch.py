#!/usr/bin/env python3
"""Bundled ``gh-issues`` skill — watch one issue for state/comment/label diffs.

Thin CLI over :mod:`sevn.integrations.github_skill.watch`.
"""

from __future__ import annotations

import argparse

from sevn.config.my_sevn import resolve_github_repo_slug
from sevn.integrations.github_skill.watch import (
    fetch_issue_state,
    snapshot_from_issue,
    watch_issue,
)
from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok

__all__ = ["fetch_issue_state", "main", "snapshot_from_issue", "watch_issue"]


def main(argv: list[str] | None = None) -> int:
    """Run gh-issues watch CLI for one issue.

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
    p.add_argument("repo", nargs="?", default=None, help="owner/repo (default: my_sevn.repo_url)")
    p.add_argument("issue_number", type=int)
    p.add_argument("--repo", dest="repo_flag", default=None, help="owner/repo override")
    args = p.parse_args(argv)
    workspace = workspace_from_env()
    try:
        repo = resolve_github_repo_slug(args.repo_flag or args.repo, workspace=workspace)
        payload = watch_issue(workspace, repo, args.issue_number)
    except (OSError, RuntimeError, ValueError) as exc:
        write_error(code="GITHUB_ISSUE_WATCH_FAILED", error=str(exc))
        return 1
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
