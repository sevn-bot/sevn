#!/usr/bin/env python3
"""Bundled ``gh-issues`` skill — view issue via authenticated ``gh`` CLI.

Module: sevn.data.bundled_skills.core.gh-issues.scripts.issue_view
Depends: argparse, asyncio, sevn.config, sevn.integrations.github_skill,
    sevn.lcm.script_cli

Exports:
    view_issue_via_gh — re-export; ``gh issue view --json`` including comment bodies.
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from sevn.config.my_sevn import resolve_github_repo_slug
from sevn.integrations.github_skill import gh_issues, resolve_github_skill_hooks
from sevn.integrations.github_skill.gh_cli import (
    GhCliMissingError,
    view_issue_via_gh,
)
from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok


def _resolve_repo_slug(explicit: str | None) -> str:
    """Return ``owner/repo`` from CLI arg or ``my_sevn.repo_url``."""
    return resolve_github_repo_slug(explicit, workspace=workspace_from_env())


def _view_via_proxy(*, repo: str, issue_number: int) -> dict[str, Any]:
    """Fall back to the existing integration proxy view path.

    Args:
        repo (str): ``owner/repo`` slug.
        issue_number (int): Issue number.

    Returns:
        dict[str, Any]: Issue payload (may nest under ``issue``).
    """
    hooks = resolve_github_skill_hooks(workspace_from_env())
    return asyncio.run(gh_issues.view_issue(hooks, repo=repo, issue_number=issue_number))


def main(argv: list[str] | None = None) -> int:
    """Run gh-issues view CLI (``gh`` first, proxy fallback).

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

    try:
        repo = _resolve_repo_slug(args.repo_flag or args.repo)
        try:
            payload = view_issue_via_gh(repo, args.issue_number)
        except GhCliMissingError:
            payload = _view_via_proxy(repo=repo, issue_number=args.issue_number)
    except (OSError, RuntimeError, ValueError) as exc:
        write_error(code="GITHUB_ISSUE_VIEW_FAILED", error=str(exc))
        return 1
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
