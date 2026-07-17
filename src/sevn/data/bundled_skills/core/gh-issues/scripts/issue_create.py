#!/usr/bin/env python3
"""Bundled ``gh-issues`` skill — create issue (templated ``gh`` CLI, proxy fallback).

Module: sevn.data.bundled_skills.core.gh-issues.scripts.issue_create
Depends: argparse, asyncio, tempfile, sevn.config, sevn.integrations.github_skill,
    sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout with ``{url, number, repo}`` on success.
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path
from typing import Any

from sevn.config.my_sevn import resolve_github_repo_slug
from sevn.integrations.github_skill import gh_issues, resolve_github_skill_hooks
from sevn.integrations.github_skill.gh_cli import (
    GhCliMissingError,
    create_issue_via_gh,
    map_gh_cli_error,
)
from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok

_SKILL_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATES_DIR = _SKILL_ROOT / "templates"
_KNOWN_TEMPLATES = frozenset({"feature", "bug", "chore"})


def _resolve_repo_slug(explicit: str | None) -> str:
    """Return ``owner/repo`` from CLI arg or ``my_sevn.repo_url``."""
    return resolve_github_repo_slug(explicit, workspace=workspace_from_env())


def _render_template(name: str, fields: dict[str, str]) -> str:
    """Render ``templates/<name>.md`` by replacing ``{{key}}`` placeholders.

    Args:
        name (str): Template id (``feature``, ``bug``, or ``chore``).
        fields (dict[str, str]): Placeholder values.

    Returns:
        str: Rendered markdown body.

    Raises:
        ValueError: When the template name is unknown or the file is missing.
    """
    key = name.strip().lower()
    if key not in _KNOWN_TEMPLATES:
        msg = f"unknown template: {name!r} (expected one of {sorted(_KNOWN_TEMPLATES)})"
        raise ValueError(msg)
    path = _TEMPLATES_DIR / f"{key}.md"
    if not path.is_file():
        msg = f"template file missing: {path}"
        raise ValueError(msg)
    text = path.read_text(encoding="utf-8")
    for placeholder, value in fields.items():
        text = text.replace("{{" + placeholder + "}}", value)
    return text


def _map_proxy_create_error(exc: BaseException, *, repo: str) -> str:
    """Map proxy/integration create failures away from bare ``proxy status 404``.

    Args:
        exc (BaseException): Exception from the proxy create path.
        repo (str): Target slug.

    Returns:
        str: Precise error string.
    """
    detail = str(exc).strip() or "github issue create failed"
    return map_gh_cli_error(detail, repo=repo)


def _normalize_proxy_payload(raw: dict[str, Any], *, repo: str) -> dict[str, Any]:
    """Normalize proxy ``create_issue`` payload to ``{url, number, repo}``.

    Args:
        raw (dict[str, Any]): Payload from :func:`gh_issues.create_issue`.
        repo (str): Fallback ``owner/repo`` slug.

    Returns:
        dict[str, Any]: ``{url, number, repo}``.

    Raises:
        RuntimeError: When the proxy payload lacks an issue number.
    """
    issue = raw.get("issue") if isinstance(raw.get("issue"), dict) else raw
    if not isinstance(issue, dict):
        issue = {}
    number = issue.get("number")
    if number is None:
        msg = f"proxy create returned no issue number for {repo}"
        raise RuntimeError(msg)
    owner = str(raw.get("owner") or repo.split("/")[0])
    name = str(raw.get("repo") or (repo.split("/")[1] if "/" in repo else repo))
    slug = f"{owner}/{name}"
    url = str(
        issue.get("html_url") or issue.get("url") or f"https://github.com/{slug}/issues/{number}"
    )
    return {"url": url, "number": int(number), "repo": slug}


def _create_via_proxy(
    *,
    repo: str,
    title: str,
    body: str,
    labels: list[str],
    assignees: list[str],
) -> dict[str, Any]:
    """Fall back to the existing integration proxy create path.

    Args:
        repo (str): ``owner/repo`` slug.
        title (str): Issue title.
        body (str): Issue body markdown.
        labels (list[str]): Labels to apply.
        assignees (list[str]): Assignees to apply.

    Returns:
        dict[str, Any]: ``{url, number, repo}``.
    """
    hooks = resolve_github_skill_hooks(workspace_from_env())
    raw = asyncio.run(
        gh_issues.create_issue(
            hooks,
            repo=repo,
            title=title,
            body=body,
            labels=labels or None,
            assignees=assignees or None,
        )
    )
    return _normalize_proxy_payload(raw, repo=repo)


def main(argv: list[str] | None = None) -> int:
    """Run gh-issues create CLI (``gh`` first, proxy fallback).

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
    p.add_argument("--repo", dest="repo_flag", default=None, help="owner/repo override")
    p.add_argument(
        "--template",
        default="feature",
        help="body template name: feature|bug|chore (default: feature)",
    )
    p.add_argument("--title", required=True)
    p.add_argument("--body", default="", help="legacy full body; used as summary when empty")
    p.add_argument("--summary", default="")
    p.add_argument("--context", default="")
    p.add_argument("--acceptance", default="", help="acceptance criteria markdown")
    p.add_argument("--source", default="")
    p.add_argument("--label", action="append", default=[])
    p.add_argument("--assignee", action="append", default=[])
    args = p.parse_args(argv)

    labels = list(args.label or [])
    assignees = list(args.assignee or [])
    try:
        repo = _resolve_repo_slug(args.repo_flag or args.repo)
        body = _render_template(
            args.template,
            {
                "title": args.title,
                "summary": args.summary or args.body or "",
                "context": args.context or "",
                "acceptance_criteria": args.acceptance or "",
                "source": args.source or "",
                "labels": ", ".join(labels) if labels else "",
            },
        )
    except (OSError, ValueError) as exc:
        write_error(code="GITHUB_ISSUE_CREATE_FAILED", error=str(exc))
        return 1

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".md",
        encoding="utf-8",
        delete=False,
    ) as handle:
        handle.write(body)
        body_path = Path(handle.name)

    try:
        try:
            payload = create_issue_via_gh(
                repo=repo,
                title=args.title,
                body_file=body_path,
                labels=labels or None,
                assignees=assignees or None,
            )
        except GhCliMissingError:
            try:
                payload = _create_via_proxy(
                    repo=repo,
                    title=args.title,
                    body=body,
                    labels=labels,
                    assignees=assignees,
                )
            except Exception as exc:  # noqa: BLE001 — proxy/httpx failures become envelope
                write_error(
                    code="GITHUB_ISSUE_CREATE_FAILED",
                    error=_map_proxy_create_error(exc, repo=repo),
                )
                return 1
        except (RuntimeError, ValueError) as exc:
            write_error(code="GITHUB_ISSUE_CREATE_FAILED", error=str(exc))
            return 1
    finally:
        body_path.unlink(missing_ok=True)

    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
