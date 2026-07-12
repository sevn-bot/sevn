"""Inbound GitHub issue ingest into the local evolution registry (`specs/35-bot-evolution.md` FL-1).

Module: sevn.evolution.github_sync
Depends: sevn.config.my_sevn, sevn.evolution.issues, sevn.integrations.github_skill.gh_issues

This is the **inbound** counterpart to ``issues.maybe_mirror_issue_to_github``: it reads issues
from GitHub via the ``gh-issues`` skill hooks and upserts them as local ``EvolutionIssue`` records
keyed on ``github.number`` (idempotent — a second import updates in place, never duplicates).

Exports:
    SyncResult — outcome counters for a ``sync_github_issues`` run.
    import_github_issue — fetch and upsert one issue by number (returns record only).
    import_github_issue_with_created — like import_github_issue but also returns the created bool.
    sync_github_issues — list and upsert many issues (skip closed unless ``state="all"``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sevn.config.my_sevn import effective_my_sevn_issues
from sevn.evolution.issues import (
    EvolutionIssue,
    IssueKind,
    list_issues,
    save_issue,
    utc_now_iso,
)
from sevn.integrations.github_skill import gh_issues

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.integrations.github_skill.hooks import GithubSkillHooks
    from sevn.workspace.layout import WorkspaceLayout


@dataclass
class SyncResult:
    """Outcome counters for a :func:`sync_github_issues` run.

    Attributes:
        imported: Issues created locally for the first time.
        updated: Existing local issues refreshed in place.
        skipped: Issues skipped (e.g. closed when ``state != "all"``).
        issues: Resulting local records for imported/updated issues.
    """

    imported: int = 0
    updated: int = 0
    skipped: int = 0
    issues: list[EvolutionIssue] | None = None


def _kind_from_labels(labels: list[str], ws: WorkspaceConfig) -> IssueKind:
    """Map GitHub label names to an evolution ``kind`` via ``my_sevn.issues.label_map``.

    Args:
        labels (list[str]): GitHub label names on the issue.
        ws (WorkspaceConfig): Workspace config supplying the label map.

    Returns:
        IssueKind: ``"feature"`` when any label maps to feature, else ``"bug"``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _kind_from_labels(["enhancement"], WorkspaceConfig.minimal())
        'feature'
        >>> _kind_from_labels(["bug"], WorkspaceConfig.minimal())
        'bug'
        >>> _kind_from_labels([], WorkspaceConfig.minimal())
        'bug'
    """
    label_map = effective_my_sevn_issues(ws).label_map
    for label in labels:
        mapped = label_map.get(label.strip().lower()) or label_map.get(label.strip())
        if mapped == "feature":
            return "feature"
    return "bug"


def _normalize_labels(raw: Any) -> list[str]:
    """Normalize a GitHub ``labels`` field into a list of label names.

    Args:
        raw (Any): ``labels`` value — list of strings or ``{"name": ...}`` objects.

    Returns:
        list[str]: Label names (empty list when the field is absent or malformed).

    Examples:
        >>> _normalize_labels([{"name": "bug"}, "enhancement"])
        ['bug', 'enhancement']
        >>> _normalize_labels(None)
        []
    """
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name:
                names.append(name)
        elif isinstance(item, str) and item:
            names.append(item)
    return names


def _find_local_by_github_number(layout: WorkspaceLayout, number: int) -> EvolutionIssue | None:
    """Return the existing local issue cross-referencing ``github.number``.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        number (int): GitHub issue number.

    Returns:
        EvolutionIssue | None: Matching record or ``None``.

    Examples:
        >>> _find_local_by_github_number.__name__
        '_find_local_by_github_number'
    """
    for issue in list_issues(layout, limit=500):
        github = issue.github
        if isinstance(github, dict) and github.get("number") == number:
            return issue
    return None


def _upsert_from_github(
    layout: WorkspaceLayout,
    ws: WorkspaceConfig,
    gh_issue: dict[str, Any],
) -> tuple[EvolutionIssue, bool]:
    """Create or update a local issue from a raw GitHub issue object.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        ws (WorkspaceConfig): Workspace config for label mapping.
        gh_issue (dict[str, Any]): Raw GitHub issue payload (``number``/``title``/...).

    Returns:
        tuple[EvolutionIssue, bool]: ``(record, created)`` where ``created`` is ``True``
            when a new local record was written.

    Examples:
        >>> _upsert_from_github.__name__
        '_upsert_from_github'
    """
    number = int(gh_issue["number"])
    title = str(gh_issue.get("title", "")).strip()
    body = str(gh_issue.get("body") or "")
    url = str(gh_issue.get("html_url") or gh_issue.get("url") or "")
    kind = _kind_from_labels(_normalize_labels(gh_issue.get("labels")), ws)
    github_ref = {"number": number, "url": url}
    now = utc_now_iso()
    existing = _find_local_by_github_number(layout, number)
    if existing is None:
        record = EvolutionIssue(
            id=f"gh-{number}",
            kind=kind,
            title=title,
            body=body,
            state="open",
            created_at=now,
            updated_at=now,
            source="github",
            github=github_ref,
        )
        return save_issue(layout, record), True
    existing.title = title
    existing.body = body
    existing.kind = kind
    existing.source = "github"
    existing.github = github_ref
    existing.updated_at = now
    return save_issue(layout, existing), False


async def import_github_issue_with_created(
    layout: WorkspaceLayout,
    hooks: GithubSkillHooks,
    *,
    repo: str,
    number: int,
    ws: WorkspaceConfig,
) -> tuple[EvolutionIssue, bool]:
    """Fetch one GitHub issue, upsert it, and return whether the record was created.

    Idempotent on ``github.number``: importing the same issue twice updates the existing
    local record in place rather than creating a duplicate.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        hooks (GithubSkillHooks): Injectable GitHub integration delegate.
        repo (str): ``owner/repo`` slug.
        number (int): GitHub issue number.
        ws (WorkspaceConfig): Workspace config for label mapping.

    Returns:
        tuple[EvolutionIssue, bool]: ``(record, created)`` where ``created`` is ``True``
            when a new local record was written for the first time.

    Examples:
        >>> import asyncio, tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"number": 42, "title": "Crash", "labels": [{"name": "bug"}]}
        >>> with tempfile.TemporaryDirectory() as td:
        ...     p = Path(td) / "sevn.json"
        ...     _ = p.write_text('{"schema_version":1}')
        ...     cfg = WorkspaceConfig.minimal()
        ...     lay = WorkspaceLayout.from_config(p, cfg)
        ...     row, created = asyncio.run(
        ...         import_github_issue_with_created(
        ...             lay,
        ...             GithubSkillHooks(integration_call=_fake),
        ...             repo="o/r",
        ...             number=42,
        ...             ws=cfg,
        ...         )
        ...     )
        ...     (row.source, row.github["number"], created)
        ('github', 42, True)
    """
    payload = await gh_issues.view_issue(hooks, repo=repo, issue_number=number)
    gh_issue = payload.get("issue")
    if not isinstance(gh_issue, dict):
        gh_issue = {"number": number}
    gh_issue.setdefault("number", number)
    return _upsert_from_github(layout, ws, gh_issue)


async def import_github_issue(
    layout: WorkspaceLayout,
    hooks: GithubSkillHooks,
    *,
    repo: str,
    number: int,
    ws: WorkspaceConfig,
) -> EvolutionIssue:
    """Fetch one GitHub issue and upsert it into the local registry.

    Idempotent on ``github.number``: importing the same issue twice updates the existing
    local record in place rather than creating a duplicate.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        hooks (GithubSkillHooks): Injectable GitHub integration delegate.
        repo (str): ``owner/repo`` slug.
        number (int): GitHub issue number.
        ws (WorkspaceConfig): Workspace config for label mapping.

    Returns:
        EvolutionIssue: Local record with ``source="github"`` and ``github.number=number``.

    Examples:
        >>> import asyncio, tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"number": 42, "title": "Crash", "labels": [{"name": "bug"}]}
        >>> with tempfile.TemporaryDirectory() as td:
        ...     p = Path(td) / "sevn.json"
        ...     _ = p.write_text('{"schema_version":1}')
        ...     cfg = WorkspaceConfig.minimal()
        ...     lay = WorkspaceLayout.from_config(p, cfg)
        ...     row = asyncio.run(
        ...         import_github_issue(
        ...             lay,
        ...             GithubSkillHooks(integration_call=_fake),
        ...             repo="o/r",
        ...             number=42,
        ...             ws=cfg,
        ...         )
        ...     )
        ...     (row.source, row.github["number"])
        ('github', 42)
    """
    record, _created = await import_github_issue_with_created(
        layout, hooks, repo=repo, number=number, ws=ws
    )
    return record


async def sync_github_issues(
    layout: WorkspaceLayout,
    hooks: GithubSkillHooks,
    *,
    repo: str,
    ws: WorkspaceConfig,
    state: str = "open",
    labels: list[str] | None = None,
) -> SyncResult:
    """List GitHub issues and upsert them into the local registry.

    Closed issues are skipped unless ``state="all"``. Upsert is idempotent on
    ``github.number`` so repeated syncs update in place.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        hooks (GithubSkillHooks): Injectable GitHub integration delegate.
        repo (str): ``owner/repo`` slug.
        ws (WorkspaceConfig): Workspace config for label mapping.
        state (str, optional): ``open``, ``closed``, or ``all``. Defaults to ``open``.
        labels (list[str] | None, optional): Optional GitHub label filter.

    Returns:
        SyncResult: Counters and the resulting local records.

    Examples:
        >>> import asyncio, tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"items": [{"number": 7, "title": "T", "state": "open"}]}
        >>> with tempfile.TemporaryDirectory() as td:
        ...     p = Path(td) / "sevn.json"
        ...     _ = p.write_text('{"schema_version":1}')
        ...     cfg = WorkspaceConfig.minimal()
        ...     lay = WorkspaceLayout.from_config(p, cfg)
        ...     res = asyncio.run(
        ...         sync_github_issues(
        ...             lay,
        ...             GithubSkillHooks(integration_call=_fake),
        ...             repo="o/r",
        ...             ws=cfg,
        ...         )
        ...     )
        ...     res.imported
        1
    """
    payload = await gh_issues.list_issues(hooks, repo=repo, state=state, labels=labels)
    rows = payload.get("issues")
    if not isinstance(rows, list):
        rows = []
    result = SyncResult(issues=[])
    assert result.issues is not None  # nosec B101 — default factory list, not optional
    for gh_issue in rows:
        if not isinstance(gh_issue, dict) or gh_issue.get("number") is None:
            continue
        if state != "all" and str(gh_issue.get("state", "open")) == "closed":
            result.skipped += 1
            continue
        record, created = _upsert_from_github(layout, ws, gh_issue)
        if created:
            result.imported += 1
        else:
            result.updated += 1
        result.issues.append(record)
    return result


__all__ = [
    "SyncResult",
    "import_github_issue",
    "import_github_issue_with_created",
    "sync_github_issues",
]
