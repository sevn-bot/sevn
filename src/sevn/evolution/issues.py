"""Evolution issue registry — local JSON (`specs/35-bot-evolution.md` §2.7).

Module: sevn.evolution.issues
Depends: json, pathlib, uuid, datetime

Exports:
    EvolutionIssue — persisted issue record.
    create_issue — create local JSON issue.
    get_issue — load one issue by id.
    list_issues — list issues newest-first.
    save_issue — persist issue JSON.
    issue_to_api_dict — Mission Control JSON shape.
    issues_dir — resolve ``workspace/.sevn/issues/``.
    maybe_mirror_issue_to_github — optional ``gh-issues`` mirror when configured.
    my_sevn_repo_slug — ``owner/repo`` slug from ``my_sevn.repo_url``.
    utc_now_iso — UTC timestamp helper.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 — runtime issue paths
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.integrations.github_skill.hooks import GithubSkillHooks
    from sevn.workspace.layout import WorkspaceLayout

IssueKind = Literal["bug", "feature"]
IssueState = Literal["open", "spec_kit", "awaiting_approval", "implementing", "done", "cancelled"]
IssueExecutor = Literal["local", "cursor_cloud"]


@dataclass
class EvolutionIssue:
    """One evolution issue persisted under ``workspace/.sevn/issues/<id>.json``."""

    id: str
    kind: IssueKind
    title: str
    body: str
    state: IssueState
    created_at: str
    updated_at: str
    source: str
    pipeline_stage: str | None = None
    approval_id: str | None = None
    executor: IssueExecutor | None = None
    cursor_job_id: str | None = None
    cursor_agent_id: str | None = None
    pr_url: str | None = None
    agent_url: str | None = None
    github: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON persistence.

        Returns:
            dict[str, Any]: JSON-safe mapping.

        Examples:
            >>> EvolutionIssue(
            ...     id="a",
            ...     kind="bug",
            ...     title="t",
            ...     body="",
            ...     state="open",
            ...     created_at="2026-01-01T00:00:00+00:00",
            ...     updated_at="2026-01-01T00:00:00+00:00",
            ...     source="manual",
            ... ).to_dict()["kind"]
            'bug'
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvolutionIssue:
        """Hydrate from persisted JSON.

        Args:
            data (dict[str, Any]): Issue JSON object.

        Returns:
            EvolutionIssue: Parsed record.

        Examples:
            >>> EvolutionIssue.from_dict(
            ...     {
            ...         "id": "x",
            ...         "kind": "feature",
            ...         "title": "t",
            ...         "body": "",
            ...         "state": "open",
            ...         "created_at": "2026-01-01T00:00:00+00:00",
            ...         "updated_at": "2026-01-01T00:00:00+00:00",
            ...         "source": "manual",
            ...     },
            ... ).kind
            'feature'
        """
        gh = data.get("github")
        github = gh if isinstance(gh, dict) else None
        kind_raw = data.get("kind", "bug")
        state_raw = data.get("state", "open")
        exec_raw = data.get("executor")
        return cls(
            id=str(data["id"]),
            kind=kind_raw if kind_raw in ("bug", "feature") else "bug",
            title=str(data.get("title", "")),
            body=str(data.get("body", "")),
            state=state_raw
            if state_raw
            in ("open", "spec_kit", "awaiting_approval", "implementing", "done", "cancelled")
            else "open",
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            source=str(data.get("source", "manual")),
            pipeline_stage=data.get("pipeline_stage"),
            approval_id=data.get("approval_id"),
            executor=exec_raw if exec_raw in ("local", "cursor_cloud") else None,
            cursor_job_id=data.get("cursor_job_id"),
            cursor_agent_id=data.get("cursor_agent_id"),
            pr_url=data.get("pr_url"),
            agent_url=data.get("agent_url"),
            github=github,
        )


def utc_now_iso() -> str:
    """Return current UTC timestamp.

    Returns:
        str: ISO-8601 timestamp.

    Examples:
        >>> "T" in utc_now_iso()
        True
    """
    return datetime.now(tz=UTC).isoformat()


def issues_dir(layout: WorkspaceLayout) -> Path:
    """Return ``<content_root>/.sevn/issues``.

    Args:
        layout (WorkspaceLayout): Workspace layout.

    Returns:
        Path: Issues directory.

    Examples:
        >>> issues_dir.__name__
        'issues_dir'
    """
    return layout.dot_sevn / "issues"


def _issue_path(layout: WorkspaceLayout, issue_id: str) -> Path:
    """Return the JSON path for ``issue_id``.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.

    Returns:
        Path: Issue file path.

    Examples:
        >>> _issue_path.__name__
        '_issue_path'
    """
    return issues_dir(layout) / f"{issue_id.strip()}.json"


def save_issue(layout: WorkspaceLayout, issue: EvolutionIssue) -> EvolutionIssue:
    """Persist one issue record.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue (EvolutionIssue): Record to write.

    Returns:
        EvolutionIssue: Same record after write.

    Examples:
        >>> save_issue.__name__
        'save_issue'
    """
    root = issues_dir(layout)
    root.mkdir(parents=True, exist_ok=True)
    path = _issue_path(layout, issue.id)
    path.write_text(json.dumps(issue.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return issue


def get_issue(layout: WorkspaceLayout, issue_id: str) -> EvolutionIssue | None:
    """Load one issue when present.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.

    Returns:
        EvolutionIssue | None: Record or ``None``.

    Examples:
        >>> get_issue.__name__
        'get_issue'
    """
    path = _issue_path(layout, issue_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    return EvolutionIssue.from_dict(data)


def list_issues(layout: WorkspaceLayout, *, limit: int = 100) -> list[EvolutionIssue]:
    """List issues sorted by ``updated_at`` descending.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        limit (int): Max rows.

    Returns:
        list[EvolutionIssue]: Newest first.

    Examples:
        >>> list_issues.__name__
        'list_issues'
    """
    root = issues_dir(layout)
    if not root.is_dir():
        return []
    cap = max(1, min(int(limit), 500))
    rows: list[EvolutionIssue] = []
    for path in root.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            rows.append(EvolutionIssue.from_dict(data))
    rows.sort(key=lambda item: item.updated_at, reverse=True)
    return rows[:cap]


def issue_to_api_dict(issue: EvolutionIssue) -> dict[str, Any]:
    """Serialize one issue for Mission Control JSON.

    Args:
        issue (EvolutionIssue): Persisted record.

    Returns:
        dict[str, Any]: API payload including executor badge fields.

    Examples:
        >>> issue_to_api_dict(
        ...     EvolutionIssue(
        ...         id="i1",
        ...         kind="feature",
        ...         title="t",
        ...         body="",
        ...         state="implementing",
        ...         created_at="2026-01-01T00:00:00+00:00",
        ...         updated_at="2026-01-01T00:00:00+00:00",
        ...         source="mc",
        ...         executor="cursor_cloud",
        ...         agent_url="https://cursor.com/agents/bc-1",
        ...     ),
        ... )["executor"]
        'cursor_cloud'
    """
    payload = issue.to_dict()
    payload["external_url"] = issue.agent_url or issue.pr_url
    return payload


def create_issue(
    layout: WorkspaceLayout,
    *,
    kind: IssueKind,
    title: str,
    body: str = "",
    source: str = "manual",
    state: IssueState = "open",
    issue_id: str | None = None,
    ws: WorkspaceConfig | None = None,
) -> EvolutionIssue:
    """Create a local issue JSON record.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        kind (IssueKind): ``bug`` or ``feature``.
        title (str): Short title.
        body (str): Markdown body.
        source (str): Provenance label.
        state (IssueState): Initial state.
        issue_id (str | None): Optional stable id.
        ws (WorkspaceConfig | None): Reserved for GitHub mirror (not used in minimal v1).

    Returns:
        EvolutionIssue: Persisted record.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as td:
        ...     p = Path(td) / "sevn.json"
        ...     _ = p.write_text('{"schema_version":1}')
        ...     lay = WorkspaceLayout.from_config(p, WorkspaceConfig.minimal())
        ...     issue = create_issue(lay, kind="bug", title="Test")
        ...     issue.kind
        'bug'
    """
    _ = ws
    now = utc_now_iso()
    iid = issue_id or uuid.uuid4().hex[:12]
    issue = EvolutionIssue(
        id=iid,
        kind=kind,
        title=title.strip(),
        body=body,
        state=state,
        created_at=now,
        updated_at=now,
        source=source,
    )
    return save_issue(layout, issue)


def my_sevn_repo_slug(ws: WorkspaceConfig) -> str:
    """Return ``owner/repo`` from ``my_sevn.repo_url``.

    Args:
        ws (WorkspaceConfig): Parsed workspace config.

    Returns:
        str: Repository slug for GitHub skill calls.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> my_sevn_repo_slug(WorkspaceConfig.minimal())
        'sevn-bot/sevn'
    """
    from sevn.config.my_sevn import effective_my_sevn
    from sevn.integrations.github_skill.client import parse_github_repo

    return "/".join(parse_github_repo(effective_my_sevn(ws).repo_url))


def _extract_github_ref(gh_payload: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize GitHub issue create response to ``{number, url}``.

    Args:
        gh_payload (dict[str, Any]): ``gh_issues.create_issue`` payload.

    Returns:
        dict[str, Any] | None: Cross-ref or ``None`` when number is absent.

    Examples:
        >>> _extract_github_ref({"issue": {"number": 1, "html_url": "https://github.com/o/r/issues/1"}})
        {'number': 1, 'url': 'https://github.com/o/r/issues/1'}
    """
    issue_obj = gh_payload.get("issue")
    if not isinstance(issue_obj, dict):
        issue_obj = gh_payload
    number = issue_obj.get("number")
    if number is None:
        return None
    url = issue_obj.get("html_url") or issue_obj.get("url") or ""
    return {"number": int(number), "url": str(url)}


async def maybe_mirror_issue_to_github(
    layout: WorkspaceLayout,
    issue: EvolutionIssue,
    ws: WorkspaceConfig,
    *,
    hooks: GithubSkillHooks | None = None,
) -> EvolutionIssue:
    """Mirror one local issue to GitHub when ``my_sevn.issues.prefer_github`` is on.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue (EvolutionIssue): Local authoritative record.
        ws (WorkspaceConfig): Workspace config for repo slug and flags.
        hooks (GithubSkillHooks | None, optional): Injectable hooks for tests.

    Returns:
        EvolutionIssue: Updated record when mirror succeeds; otherwise unchanged.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.integrations.github_skill.hooks import GithubSkillHooks
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> import tempfile
        >>> async def _fake(_m: str, _a: dict[str, object]) -> dict[str, object]:
        ...     return {"number": 7, "html_url": "https://github.com/o/r/issues/7"}
        >>> with tempfile.TemporaryDirectory() as td:
        ...     p = Path(td) / "sevn.json"
        ...     _ = p.write_text('{"schema_version":1}')
        ...     cfg = WorkspaceConfig.minimal()
        ...     lay = WorkspaceLayout.from_config(p, cfg)
        ...     created = create_issue(lay, kind="bug", title="T")
        ...     mirrored = asyncio.run(
        ...         maybe_mirror_issue_to_github(
        ...             lay,
        ...             created,
        ...             cfg,
        ...             hooks=GithubSkillHooks(integration_call=_fake),
        ...         )
        ...     )
        ...     mirrored.github == {"number": 7, "url": "https://github.com/o/r/issues/7"}
        True
    """
    from sevn.config.my_sevn import effective_my_sevn
    from sevn.integrations.github_skill import gh_issues, resolve_github_skill_hooks

    my = effective_my_sevn(ws)
    issues_cfg = my.issues
    if issues_cfg is not None and not issues_cfg.prefer_github:
        return issue
    resolved = hooks if hooks is not None else resolve_github_skill_hooks(ws)
    if resolved.integration_call is None:
        return issue
    try:
        gh_payload = await gh_issues.create_issue(
            resolved,
            repo=my_sevn_repo_slug(ws),
            title=issue.title,
            body=issue.body,
        )
    except Exception as exc:
        logger.warning(f"evolution github mirror skipped for {issue.id}: {exc}")
        return issue
    ref = _extract_github_ref(gh_payload)
    if ref is None:
        return issue
    issue.github = ref
    issue.updated_at = utc_now_iso()
    return save_issue(layout, issue)


__all__ = [
    "EvolutionIssue",
    "create_issue",
    "get_issue",
    "issue_to_api_dict",
    "issues_dir",
    "list_issues",
    "maybe_mirror_issue_to_github",
    "my_sevn_repo_slug",
    "save_issue",
    "utc_now_iso",
]
