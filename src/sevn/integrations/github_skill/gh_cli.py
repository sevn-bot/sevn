"""Authenticated ``gh`` CLI helpers for issue create/view (W5/W6 fast path).

Module: sevn.integrations.github_skill.gh_cli
Depends: json, re, subprocess

Exports:
    GhCliMissingError — raised when the ``gh`` binary is not on PATH.
    map_gh_cli_error — map ``gh`` stderr to a precise operator message.
    run_gh — run a fixed ``gh`` argv and return ``CompletedProcess``.
    create_issue_via_gh — create an issue via authenticated ``gh issue create``.
    view_issue_via_gh — view an issue via authenticated ``gh issue view --json``.
"""

from __future__ import annotations

import json
import re
import subprocess  # nosec B404 — fixed ``gh`` argv only; no shell
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

_ISSUE_URL_RE = re.compile(
    r"https://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/issues/(?P<number>\d+)",
    re.IGNORECASE,
)

_ISSUE_VIEW_JSON_FIELDS = "number,title,state,url,updatedAt,labels,assignees,comments"


class GhCliMissingError(RuntimeError):
    """Raised when the ``gh`` binary is absent from ``PATH``."""


def map_gh_cli_error(
    stderr: str,
    *,
    repo: str,
    labels: list[str] | None = None,
) -> str:
    """Map ``gh`` CLI stderr to a precise, non-proxy error string.

    Neutral helper shared by create/view (and other) ``gh`` call sites.

    Args:
        stderr (str): Combined stderr (and optionally stdout) from ``gh``.
        repo (str): ``owner/repo`` slug used in the call.
        labels (list[str] | None, optional): Labels passed to ``gh`` (for mapping).

    Returns:
        str: Operator-facing error that never reads as bare ``proxy status 404``.

    Examples:
        >>> map_gh_cli_error("please run: gh auth login", repo="o/r")
        'gh not authenticated (run: gh auth login)'
        >>> map_gh_cli_error("could not resolve to a Repository", repo="o/r")
        'repository not found: o/r'
    """
    text = (stderr or "").strip()
    lowered = text.lower()
    if (
        "gh auth login" in lowered
        or "not logged into" in lowered
        or "to get started with github cli" in lowered
        or "authentication required" in lowered
        or "http 401" in lowered
    ):
        return "gh not authenticated (run: gh auth login)"
    if (
        "could not resolve to a repository" in lowered
        or "repository not found" in lowered
        or ("not found" in lowered and "label" not in lowered)
        or "http 404" in lowered
    ):
        return f"repository not found: {repo}"
    if "label" in lowered and (
        "not found" in lowered
        or "does not exist" in lowered
        or "invalid" in lowered
        or "could not be found" in lowered
    ):
        for label in labels or []:
            if label.lower() in lowered:
                return f"label does not exist: {label}"
        if labels:
            return f"label does not exist: {labels[0]}"
        return "label does not exist: (unknown)"
    if "proxy status" in lowered:
        return f"repository not found: {repo}"
    return text or f"gh command failed for {repo}"


def run_gh(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a fixed ``gh`` argv (no shell) and return the completed process.

    Args:
        cmd (list[str]): Argv beginning with ``gh``.

    Returns:
        subprocess.CompletedProcess[str]: Captured stdout/stderr result.

    Raises:
        GhCliMissingError: When ``gh`` is not installed / not on ``PATH``.

    Examples:
        >>> isinstance(GhCliMissingError("missing"), RuntimeError)
        True
    """
    try:
        return subprocess.run(  # nosec B603 — fixed ``gh`` argv; no shell
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GhCliMissingError("gh binary not found on PATH") from exc


def create_issue_via_gh(
    *,
    repo: str,
    title: str,
    body_file: Path,
    labels: list[str] | None = None,
    assignees: list[str] | None = None,
) -> dict[str, Any]:
    """Create a GitHub issue via ``gh issue create`` (authenticated CLI fast path).

    Args:
        repo (str): ``owner/repo`` slug.
        title (str): Issue title.
        body_file (Path): Path to a rendered markdown body file.
        labels (list[str] | None, optional): Label names to apply.
        assignees (list[str] | None, optional): Assignee usernames.

    Returns:
        dict[str, Any]: ``{url, number, repo}`` parsed from the ``gh`` stdout URL.

    Raises:
        GhCliMissingError: When ``gh`` is not installed / not on ``PATH``.
        RuntimeError: When ``gh`` exits non-zero (message already mapped).
        ValueError: When stdout does not contain a parseable issue URL.

    Examples:
        >>> isinstance(GhCliMissingError("missing"), RuntimeError)
        True
    """
    cmd: list[str] = [
        "gh",
        "issue",
        "create",
        "--repo",
        repo,
        "--title",
        title,
        "--body-file",
        str(body_file),
    ]
    for label in labels or []:
        cmd.extend(["--label", label])
    for assignee in assignees or []:
        cmd.extend(["--assignee", assignee])
    completed = run_gh(cmd)
    if completed.returncode != 0:
        detail = map_gh_cli_error(
            (completed.stderr or "") + "\n" + (completed.stdout or ""),
            repo=repo,
            labels=labels,
        )
        raise RuntimeError(detail)
    url = ""
    for line in reversed((completed.stdout or "").splitlines()):
        candidate = line.strip()
        if candidate.startswith("http"):
            url = candidate
            break
    if not url:
        msg = f"gh issue create returned no URL for {repo}"
        raise ValueError(msg)
    match = _ISSUE_URL_RE.search(url)
    if match is None:
        msg = f"could not parse issue URL from gh output: {url!r}"
        raise ValueError(msg)
    return {
        "url": url,
        "number": int(match.group("number")),
        "repo": f"{match.group('owner')}/{match.group('repo')}",
    }


def view_issue_via_gh(repo: str, issue_number: int) -> dict[str, Any]:
    """Fetch one issue via ``gh issue view --json`` (includes comment bodies).

    Args:
        repo (str): ``owner/repo`` slug.
        issue_number (int): Issue number.

    Returns:
        dict[str, Any]: Parsed ``gh`` JSON payload (number, title, state, url,
            updatedAt, labels, assignees, comments with bodies).

    Raises:
        GhCliMissingError: When ``gh`` is not installed / not on ``PATH``.
        RuntimeError: When ``gh`` exits non-zero (message already mapped).
        ValueError: When stdout is not valid JSON.

    Examples:
        >>> view_issue_via_gh.__name__
        'view_issue_via_gh'
    """
    cmd: list[str] = [
        "gh",
        "issue",
        "view",
        str(int(issue_number)),
        "--repo",
        repo,
        "--json",
        _ISSUE_VIEW_JSON_FIELDS,
    ]
    completed = run_gh(cmd)
    if completed.returncode != 0:
        detail = map_gh_cli_error(
            (completed.stderr or "") + "\n" + (completed.stdout or ""),
            repo=repo,
        )
        raise RuntimeError(detail)
    raw = (completed.stdout or "").strip()
    if not raw:
        msg = f"gh issue view returned empty JSON for {repo}#{issue_number}"
        raise ValueError(msg)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"gh issue view returned invalid JSON for {repo}#{issue_number}"
        raise ValueError(msg) from exc
    if not isinstance(payload, dict):
        msg = f"gh issue view JSON must be an object for {repo}#{issue_number}"
        raise ValueError(msg)
    return payload


__all__ = [
    "GhCliMissingError",
    "create_issue_via_gh",
    "map_gh_cli_error",
    "run_gh",
    "view_issue_via_gh",
]
