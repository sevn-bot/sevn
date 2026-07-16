#!/usr/bin/env python3
"""Bundled ``gh-issues`` skill — maintain the watched-issue set.

Module: sevn.data.bundled_skills.core.gh-issues.scripts.issue_track
Depends: argparse, json, pathlib, sevn.config, sevn.lcm.script_cli

Exports:
    tracked_path — path to ``.sevn/gh-watch/tracked.json``.
    load_tracked — read the tracked issue list.
    save_tracked — write the tracked issue list.
    main — CLI ``--add`` / ``--remove`` / ``--list``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sevn.config.loader import load_workspace
from sevn.config.my_sevn import default_github_repo_slug
from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok


def tracked_path(workspace: Path) -> Path:
    """Return ``.sevn/gh-watch/tracked.json`` under ``workspace``.

    Args:
        workspace (Path): Workspace root.

    Returns:
        Path: Tracked-issues JSON path.

    Examples:
        >>> from pathlib import Path
        >>> tracked_path(Path("/ws")).as_posix().endswith(".sevn/gh-watch/tracked.json")
        True
    """
    return workspace / ".sevn" / "gh-watch" / "tracked.json"


def _resolve_repo_slug(explicit: str | None) -> str:
    """Return ``owner/repo`` from CLI arg or ``my_sevn.repo_url``.

    Args:
        explicit (str | None): Explicit slug when provided.

    Returns:
        str: GitHub ``owner/repo`` slug.
    """
    if explicit and explicit.strip():
        return explicit.strip()
    workspace = workspace_from_env()
    cfg, _layout = load_workspace(sevn_json=workspace / "sevn.json")
    return default_github_repo_slug(cfg)


def load_tracked(workspace: Path) -> list[dict[str, Any]]:
    """Load tracked issues from ``tracked.json``.

    Args:
        workspace (Path): Workspace root.

    Returns:
        list[dict[str, Any]]: Rows with ``repo`` and ``number``.
    """
    path = tracked_path(workspace)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, list):
        items: list[Any] = raw
    elif isinstance(raw, dict):
        maybe = raw.get("issues")
        items = maybe if isinstance(maybe, list) else []
    else:
        items = []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        repo = str(item.get("repo") or "").strip()
        number = item.get("number")
        if not repo or number is None:
            continue
        try:
            out.append({"repo": repo, "number": int(number)})
        except (TypeError, ValueError):
            continue
    return out


def save_tracked(workspace: Path, issues: list[dict[str, Any]]) -> Path:
    """Persist tracked issues to ``tracked.json``.

    Args:
        workspace (Path): Workspace root.
        issues (list[dict[str, Any]]): Rows with ``repo`` and ``number``.

    Returns:
        Path: Written file path.
    """
    path = tracked_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"issues": [{"repo": i["repo"], "number": int(i["number"])} for i in issues]}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


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
        repo = _resolve_repo_slug(args.repo)
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
