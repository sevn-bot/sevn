#!/usr/bin/env python3
"""Bundled ``gh-issues`` skill — watch one issue for state/comment/label diffs.

Module: sevn.data.bundled_skills.core.gh-issues.scripts.issue_watch
Depends: argparse, json, pathlib, sevn.config, sevn.integrations.github_skill,
    sevn.lcm.script_cli

Exports:
    fetch_issue_state — current issue snapshot via ``gh``.
    watch_issue — diff vs ``.sevn/gh-watch/<owner>/<repo>/<n>.json``.
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sevn.config.loader import load_workspace
from sevn.config.my_sevn import default_github_repo_slug
from sevn.integrations.github_skill.github_manager import view_issue_via_gh
from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok


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


def _split_repo(repo: str) -> tuple[str, str]:
    """Split ``owner/repo`` into owner and name.

    Args:
        repo (str): ``owner/repo`` slug.

    Returns:
        tuple[str, str]: ``(owner, name)``.

    Raises:
        ValueError: When the slug is not ``owner/repo``.
    """
    parts = repo.strip().split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        msg = f"invalid repo slug: {repo!r} (expected owner/repo)"
        raise ValueError(msg)
    return parts[0], parts[1]


def _watch_state_path(workspace: Path, repo: str, issue_number: int) -> Path:
    """Return the last-seen state file for one issue.

    Args:
        workspace (Path): Workspace root.
        repo (str): ``owner/repo`` slug.
        issue_number (int): Issue number.

    Returns:
        Path: ``.sevn/gh-watch/<owner>/<repo>/<n>.json``.
    """
    owner, name = _split_repo(repo)
    return workspace / ".sevn" / "gh-watch" / owner / name / f"{int(issue_number)}.json"


def _label_names(raw: object) -> list[str]:
    """Normalize label objects/strings to sorted unique names.

    Args:
        raw (object): ``gh`` labels list or prior-state string list.

    Returns:
        list[str]: Sorted label names.
    """
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            name = item.get("name")
            if name:
                names.append(str(name))
        elif item is not None:
            names.append(str(item))
    return sorted(set(names))


def _comment_id(comment: object) -> str | None:
    """Extract a stable comment id from a ``gh`` comment object.

    Args:
        comment (object): One comment dict.

    Returns:
        str | None: Comment id when present.
    """
    if not isinstance(comment, dict):
        return None
    for key in ("id", "databaseId", "url"):
        value = comment.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def snapshot_from_issue(current: dict[str, Any]) -> dict[str, Any]:
    """Build the persisted last-seen snapshot from a live issue payload.

    Args:
        current (dict[str, Any]): Issue JSON from ``gh`` / :func:`fetch_issue_state`.

    Returns:
        dict[str, Any]: ``state``, ``updatedAt``, ``comment_count``,
            ``last_comment_id``, ``labels``.

    Examples:
        >>> snapshot_from_issue(
        ...     {"state": "OPEN", "updatedAt": "t", "labels": [{"name": "bug"}],
        ...      "comments": [{"id": "C_1"}]}
        ... )["comment_count"]
        1
    """
    raw_comments = current.get("comments")
    comments: list[Any] = raw_comments if isinstance(raw_comments, list) else []
    last_id: str | None = None
    if comments:
        last_id = _comment_id(comments[-1])
    return {
        "state": str(current.get("state") or ""),
        "updatedAt": str(current.get("updatedAt") or ""),
        "comment_count": len(comments),
        "last_comment_id": last_id,
        "labels": _label_names(current.get("labels")),
    }


def _diff_snapshots(
    previous: dict[str, Any] | None,
    current_snap: dict[str, Any],
    *,
    live: dict[str, Any],
) -> dict[str, Any]:
    """Compute operator-facing changes between previous and current snapshots.

    Args:
        previous (dict[str, Any] | None): Last-seen snapshot (or ``None``).
        current_snap (dict[str, Any]): Fresh snapshot.
        live (dict[str, Any]): Full live issue payload (for new comment bodies).

    Returns:
        dict[str, Any]: Sparse change map (empty when unchanged).
    """
    if previous is None:
        return {}
    changes: dict[str, Any] = {}
    if str(previous.get("state") or "") != current_snap["state"]:
        changes["state"] = {
            "from": previous.get("state"),
            "to": current_snap["state"],
        }
    if str(previous.get("updatedAt") or "") != current_snap["updatedAt"]:
        changes["updatedAt"] = {
            "from": previous.get("updatedAt"),
            "to": current_snap["updatedAt"],
        }
    prev_labels = _label_names(previous.get("labels"))
    if prev_labels != current_snap["labels"]:
        added = sorted(set(current_snap["labels"]) - set(prev_labels))
        removed = sorted(set(prev_labels) - set(current_snap["labels"]))
        changes["labels"] = {"added": added, "removed": removed}
    prev_count = int(previous.get("comment_count") or 0)
    prev_last = previous.get("last_comment_id")
    if current_snap["comment_count"] != prev_count or current_snap["last_comment_id"] != prev_last:
        raw_comments = live.get("comments")
        comments: list[Any] = raw_comments if isinstance(raw_comments, list) else []
        new_comments: list[dict[str, Any]] = []
        if prev_last is None:
            new_comments = [c for c in comments if isinstance(c, dict)]
        else:
            seen_prev = False
            for comment in comments:
                if not isinstance(comment, dict):
                    continue
                cid = _comment_id(comment)
                if not seen_prev:
                    if cid == str(prev_last):
                        seen_prev = True
                    continue
                new_comments.append(comment)
            if not seen_prev and current_snap["comment_count"] > prev_count:
                new_comments = [c for c in comments[prev_count:] if isinstance(c, dict)]
        changes["comments"] = {
            "from_count": prev_count,
            "to_count": current_snap["comment_count"],
            "last_comment_id": current_snap["last_comment_id"],
            "new_comments": [
                {
                    "id": _comment_id(c),
                    "body": c.get("body") if isinstance(c, dict) else None,
                }
                for c in new_comments
            ],
        }
    return changes


def fetch_issue_state(repo: str, issue_number: int) -> dict[str, Any]:
    """Fetch the current issue payload via authenticated ``gh``.

    Args:
        repo (str): ``owner/repo`` slug.
        issue_number (int): Issue number.

    Returns:
        dict[str, Any]: Live issue JSON (includes comment bodies).

    Examples:
        >>> callable(fetch_issue_state)
        True
    """
    return view_issue_via_gh(repo, int(issue_number))


def watch_issue(workspace: Path, repo: str, issue_number: int) -> dict[str, Any]:
    """Diff live issue state against ``.sevn/gh-watch/.../<n>.json`` and persist.

    Args:
        workspace (Path): Workspace root (holds ``.sevn/gh-watch``).
        repo (str): ``owner/repo`` slug.
        issue_number (int): Issue number.

    Returns:
        dict[str, Any]: ``{repo, number, changes, changed, snapshot}``.

    Examples:
        >>> callable(watch_issue)
        True
    """
    live = fetch_issue_state(repo, int(issue_number))
    snap = snapshot_from_issue(live)
    path = _watch_state_path(workspace, repo, int(issue_number))
    previous: dict[str, Any] | None = None
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                previous = loaded
        except (OSError, json.JSONDecodeError):
            previous = None
    changes = _diff_snapshots(previous, snap, live=live)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "repo": repo,
        "number": int(issue_number),
        "changes": changes,
        "changed": bool(changes),
        "snapshot": snap,
    }


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
        repo = _resolve_repo_slug(args.repo_flag or args.repo)
        payload = watch_issue(workspace, repo, args.issue_number)
    except (OSError, RuntimeError, ValueError) as exc:
        write_error(code="GITHUB_ISSUE_WATCH_FAILED", error=str(exc))
        return 1
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
