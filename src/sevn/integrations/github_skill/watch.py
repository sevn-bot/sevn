"""GitHub issue watch/track state for cron + ``gh-issues`` skill scripts (D13).

Module: sevn.integrations.github_skill.watch
Depends: json, pathlib, sevn.integrations.github_skill.github_manager

Exports:
    tracked_path — path to ``.sevn/gh-watch/tracked.json``.
    load_tracked — read the tracked issue list.
    save_tracked — write the tracked issue list.
    watch_state_path — last-seen state file for one issue.
    snapshot_from_issue — persistable snapshot from a live issue payload.
    fetch_issue_state — current issue snapshot via ``gh``.
    watch_issue — diff vs last-seen state and persist.
    run_tracked_watch — watch every tracked issue; return changed diffs.
"""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003 — used in doctests and at runtime
from typing import Any

from sevn.integrations.github_skill.client import parse_github_repo
from sevn.integrations.github_skill.gh_cli import view_issue_via_gh


def tracked_path(workspace: Path) -> Path:
    """Return ``.sevn/gh-watch/tracked.json`` under ``workspace``.

    Args:
        workspace (Path): Workspace root.

    Returns:
        Path: Tracked-issues JSON path.

    Examples:
        >>> tracked_path(Path("/ws")).as_posix().endswith(".sevn/gh-watch/tracked.json")
        True
    """
    return workspace / ".sevn" / "gh-watch" / "tracked.json"


def watch_state_path(workspace: Path, repo: str, issue_number: int) -> Path:
    """Return the last-seen state file for one issue.

    Args:
        workspace (Path): Workspace root.
        repo (str): ``owner/repo`` slug (or URL / SCP form accepted by
            :func:`~sevn.integrations.github_skill.client.parse_github_repo`).
        issue_number (int): Issue number.

    Returns:
        Path: ``.sevn/gh-watch/<owner>/<repo>/<n>.json``.

    Examples:
        >>> p = watch_state_path(Path("/ws"), "o/r", 1)
        >>> p.as_posix().endswith(".sevn/gh-watch/o/r/1.json")
        True
    """
    owner, name = parse_github_repo(repo)
    return workspace / ".sevn" / "gh-watch" / owner / name / f"{int(issue_number)}.json"


def load_tracked(workspace: Path) -> list[dict[str, Any]]:
    """Load tracked issues from ``tracked.json``.

    Args:
        workspace (Path): Workspace root.

    Returns:
        list[dict[str, Any]]: Rows with ``repo`` and ``number``.

    Examples:
        >>> load_tracked(Path("/no/such/ws"))
        []
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

    Examples:
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> save_tracked(root, [{"repo": "o/r", "number": 1}]).is_file()
        True
    """
    path = tracked_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"issues": [{"repo": i["repo"], "number": int(i["number"])} for i in issues]}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _label_names(raw: object) -> list[str]:
    """Normalize label objects/strings to sorted unique names.

    Args:
        raw (object): ``gh`` labels list or prior-state string list.

    Returns:
        list[str]: Sorted unique label names.

    Examples:
        >>> _label_names([{"name": "bug"}, "bug"])
        ['bug']
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

    Examples:
        >>> _comment_id({"id": "C_1"})
        'C_1'
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

    Examples:
        >>> _diff_snapshots(None, {"state": "OPEN"}, live={})
        {}
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
        >>> fetch_issue_state.__name__
        'fetch_issue_state'
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
        >>> watch_issue.__name__
        'watch_issue'
    """
    live = fetch_issue_state(repo, int(issue_number))
    snap = snapshot_from_issue(live)
    path = watch_state_path(workspace, repo, int(issue_number))
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


def run_tracked_watch(workspace: Path) -> list[dict[str, Any]]:
    """Watch every tracked issue and return only entries with changes.

    Args:
        workspace (Path): Workspace root.

    Returns:
        list[dict[str, Any]]: Diff payloads where ``changed`` is true.

    Examples:
        >>> run_tracked_watch(Path("/no/such/ws"))
        []
    """
    collected: list[dict[str, Any]] = []
    for item in load_tracked(workspace):
        result = watch_issue(workspace, str(item["repo"]), int(item["number"]))
        if isinstance(result, dict) and result.get("changed"):
            collected.append(result)
    return collected


__all__ = [
    "fetch_issue_state",
    "load_tracked",
    "run_tracked_watch",
    "save_tracked",
    "snapshot_from_issue",
    "tracked_path",
    "watch_issue",
    "watch_state_path",
]
