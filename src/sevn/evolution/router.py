"""Evolution executor routing — local vs Cursor Cloud (`specs/35-bot-evolution.md` §4.4).

Module: sevn.evolution.router
Depends: sevn.config.my_sevn, sevn.evolution.issues, sevn.evolution.spec_kit,
    sevn.integrations.cursor_cloud.client, sevn.integrations.cursor_cloud.config

Exports:
    ExecutorBlockedError — cursor_cloud unavailable for configured route.
    resolve_executor — map issue kind to ``local`` or ``cursor_cloud``.
    resolve_target_repo_url — repo URL for cloud agent launch.
    build_cursor_cloud_prompt — issue body + spec-kit paths + constitution excerpt.
    launch_cursor_cloud_for_issue — create cloud agent and persist issue linkage.
    poll_cursor_cloud_for_issue — refresh job status and update issue row.
    dispatch_cursor_cloud_implement — launch + optional poll for one issue.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal

from sevn.config.my_sevn import effective_my_sevn
from sevn.evolution.issues import EvolutionIssue, get_issue, save_issue, utc_now_iso
from sevn.evolution.spec_kit import load_constitution
from sevn.integrations.cursor_cloud.client import create_cloud_agent, refresh_job_status
from sevn.integrations.cursor_cloud.config import load_cursor_cloud_settings
from sevn.integrations.cursor_cloud.jobs import CursorCloudJob, get_job

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from sevn.config.workspace_config import EvolutionExecutorKind, WorkspaceConfig
    from sevn.workspace.layout import WorkspaceLayout

IssueKind = Literal["bug", "feature"]

_CURSOR_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"FINISHED", "FAILED", "CANCELLED", "CANCELLED_BY_USER", "ERROR", "DONE"},
)

_CONSTITUTION_EXCERPT_CHARS = 4000
_ARTEFACT_EXCERPT_CHARS = 3000  # FL-4C.5 — max chars per spec-kit artefact embedded in prompt


class ExecutorBlockedError(RuntimeError):
    """Raised when ``cursor_cloud`` is configured but unavailable."""


def resolve_executor(ws: WorkspaceConfig, kind: IssueKind) -> EvolutionExecutorKind:
    """Return configured executor for a bug or feature issue.

    Args:
        ws (WorkspaceConfig): Parsed workspace config.
        kind (IssueKind): Issue kind.

    Returns:
        EvolutionExecutorKind: ``local`` or ``cursor_cloud``.

    Examples:
        >>> from sevn.config.workspace_config import (
        ...     MySevnExecutorsWorkspaceConfig,
        ...     MySevnWorkspaceConfig,
        ...     WorkspaceConfig,
        ... )
        >>> resolve_executor(WorkspaceConfig.minimal(), "bug")
        'local'
        >>> ws = WorkspaceConfig.minimal(
        ...     my_sevn=MySevnWorkspaceConfig(
        ...         executors=MySevnExecutorsWorkspaceConfig(feature="cursor_cloud"),
        ...     ),
        ... )
        >>> resolve_executor(ws, "feature")
        'cursor_cloud'
    """
    my = effective_my_sevn(ws)
    executors = my.executors
    if executors is None:
        return "cursor_cloud" if kind == "feature" else "local"
    if kind == "feature":
        return executors.feature
    return executors.bug


def resolve_target_repo_url(ws: WorkspaceConfig, workspace: Path) -> str:
    """Resolve repository URL for Cursor Cloud launch.

    Prefers ``my_sevn.repo_url``, then ``skills.cursor_cloud.default_repo_url``.

    Args:
        ws (WorkspaceConfig): Parsed workspace config.
        workspace (Path): Workspace content root.

    Returns:
        str: Non-empty GitHub/GitLab URL.

    Raises:
        ExecutorBlockedError: When no repo URL is configured.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> resolve_target_repo_url(
        ...     WorkspaceConfig.minimal(),
        ...     Path("."),
        ... ).startswith("https://")
        True
    """
    my = effective_my_sevn(ws)
    repo = (my.repo_url or "").strip()
    if repo:
        return repo
    settings, _cfg = load_cursor_cloud_settings(workspace)
    fallback = (settings.default_repo_url or "").strip()
    if fallback:
        return fallback
    msg = "no repository URL: set my_sevn.repo_url or skills.cursor_cloud.default_repo_url"
    raise ExecutorBlockedError(msg)


def _feature_artefact_paths(
    ws: WorkspaceConfig, layout: WorkspaceLayout, issue_id: str
) -> list[str]:
    """List relative spec-kit artefact paths for an issue when present.

    Args:
        ws (WorkspaceConfig): Parsed workspace.
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.

    Returns:
        list[str]: Relative paths under repo or workspace.

    Examples:
        >>> _feature_artefact_paths.__name__
        '_feature_artefact_paths'
    """
    from sevn.evolution.spec_kit import _effective_spec_kit, _try_resolve_repo_root

    features_rel = _effective_spec_kit(ws).features_dir.replace("\\", "/").strip("/")
    names = ("spec.md", "plan.md", "tasks.md", "constitution.md")
    paths: list[str] = []
    repo = _try_resolve_repo_root()
    if repo is not None:
        base = repo / features_rel / issue_id
        if base.is_dir():
            for name in names:
                candidate = base / name
                if candidate.is_file():
                    paths.append(str(candidate.relative_to(repo)))
    mirror = layout.content_root / features_rel / issue_id
    if mirror.is_dir():
        for name in names:
            candidate = mirror / name
            if candidate.is_file():
                rel = f"{features_rel}/{issue_id}/{name}"
                if rel not in paths:
                    paths.append(rel)
    return paths


def _read_artefact_content(
    ws: WorkspaceConfig, layout: WorkspaceLayout, issue_id: str
) -> list[tuple[str, str]]:
    """Return ``(path, truncated_content)`` pairs for spec-kit artefacts.

    Embeds truncated file content rather than path-only references so the
    Cursor Cloud agent can act without workspace mirror access (FL-4C.5).

    Args:
        ws (WorkspaceConfig): Parsed workspace.
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.

    Returns:
        list[tuple[str, str]]: ``(relative_path, content)`` pairs for each artefact.

    Examples:
        >>> _read_artefact_content.__name__
        '_read_artefact_content'
    """
    from sevn.evolution.spec_kit import _effective_spec_kit, _try_resolve_repo_root

    features_rel = _effective_spec_kit(ws).features_dir.replace("\\", "/").strip("/")
    names = ("spec.md", "plan.md", "tasks.md", "constitution.md")
    results: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _read_candidate(path: Path, rel: str) -> None:
        if rel in seen or not path.is_file():
            return
        seen.add(rel)
        raw = path.read_text(encoding="utf-8", errors="replace").strip()
        if len(raw) > _ARTEFACT_EXCERPT_CHARS:
            raw = raw[:_ARTEFACT_EXCERPT_CHARS] + "\n\n…(truncated)"
        results.append((rel, raw))

    repo = _try_resolve_repo_root()
    if repo is not None:
        base = repo / features_rel / issue_id
        if base.is_dir():
            for name in names:
                candidate = base / name
                _read_candidate(candidate, str(candidate.relative_to(repo)))

    mirror = layout.content_root / features_rel / issue_id
    if mirror.is_dir():
        for name in names:
            candidate = mirror / name
            rel = f"{features_rel}/{issue_id}/{name}"
            _read_candidate(candidate, rel)

    return results


def build_cursor_cloud_prompt(
    ws: WorkspaceConfig,
    layout: WorkspaceLayout,
    issue: EvolutionIssue,
) -> str:
    """Compose cloud agent prompt from issue body, spec-kit artefact content, and constitution excerpt.

    FL-4C.5: artefact *content* (truncated) is now embedded directly instead of
    path references only, so the Cursor Cloud agent can act even when it cannot
    access the operator workspace mirror.

    Args:
        ws (WorkspaceConfig): Parsed workspace.
        layout (WorkspaceLayout): Workspace layout.
        issue (EvolutionIssue): Issue being implemented.

    Returns:
        str: Prompt text for ``agents.create``.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(build_cursor_cloud_prompt)
        True
    """
    parts: list[str] = [
        f"# Evolution issue {issue.id} ({issue.kind})",
        f"## Title\n{issue.title}",
        f"## Body\n{issue.body.strip() or '(empty)'}",
    ]
    artefact_contents = _read_artefact_content(ws, layout, issue.id)
    if artefact_contents:
        artefact_blocks = []
        for rel_path, content in artefact_contents:
            artefact_blocks.append(f"### `{rel_path}`\n\n{content}")
        parts.append("## Spec-kit artefacts\n\n" + "\n\n---\n\n".join(artefact_blocks))
    else:
        # Fallback: path list when content is unavailable (no local artefacts yet).
        artefact_paths = _feature_artefact_paths(ws, layout, issue.id)
        if artefact_paths:
            parts.append(
                "## Spec-kit artefact paths (content not yet available)\n"
                + "\n".join(f"- `{p}`" for p in artefact_paths)
            )
    constitution = load_constitution(ws, layout)
    excerpt = constitution.text.strip()
    if len(excerpt) > _CONSTITUTION_EXCERPT_CHARS:
        excerpt = excerpt[:_CONSTITUTION_EXCERPT_CHARS] + "\n\n…(truncated)"
    parts.append(f"## Constitution excerpt ({constitution.source})\n{excerpt}")
    return "\n\n".join(parts).strip()


def _ensure_cursor_cloud_enabled(workspace: Path) -> None:
    """Raise when the cursor_cloud skill gate is off.

    Args:
        workspace (Path): Content root.

    Raises:
        ExecutorBlockedError: When disabled.

    Examples:
        >>> _ensure_cursor_cloud_enabled.__name__
        '_ensure_cursor_cloud_enabled'
    """
    settings, _cfg = load_cursor_cloud_settings(workspace)
    if not settings.enabled:
        msg = "skills.cursor_cloud.enabled is false"
        raise ExecutorBlockedError(msg)


def launch_cursor_cloud_for_issue(
    conn: sqlite3.Connection,
    ws: WorkspaceConfig,
    layout: WorkspaceLayout,
    issue: EvolutionIssue,
    *,
    session_key: str = "",
) -> EvolutionIssue:
    """Launch Cursor Cloud agent for an issue and persist linkage on the issue row.

    Args:
        conn (sqlite3.Connection): Workspace SQLite.
        ws (WorkspaceConfig): Parsed workspace.
        layout (WorkspaceLayout): Workspace layout.
        issue (EvolutionIssue): Issue entering implement stage.
        session_key (str): Optional session attribution.

    Returns:
        EvolutionIssue: Updated issue with ``cursor_*`` fields.

    Raises:
        ExecutorBlockedError: When cloud delegation is unavailable.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(launch_cursor_cloud_for_issue)
        True
    """
    _ensure_cursor_cloud_enabled(layout.content_root)
    repo_url = resolve_target_repo_url(ws, layout.content_root)
    settings, _cfg = load_cursor_cloud_settings(layout.content_root)
    prompt = build_cursor_cloud_prompt(ws, layout, issue)
    job = create_cloud_agent(
        conn,
        layout.content_root,
        prompt=prompt,
        repo_url=repo_url,
        starting_ref=settings.default_ref,
        session_key=session_key,
    )
    issue.executor = "cursor_cloud"
    issue.cursor_job_id = job.job_id
    issue.cursor_agent_id = job.cursor_agent_id
    issue.agent_url = job.agent_url
    issue.pr_url = job.pr_url
    issue.state = "implementing"
    issue.pipeline_stage = "implementing"
    issue.updated_at = utc_now_iso()
    return save_issue(layout, issue)


def poll_cursor_cloud_for_issue(
    conn: sqlite3.Connection,
    layout: WorkspaceLayout,
    issue: EvolutionIssue,
    *,
    ws: WorkspaceConfig | None = None,
) -> EvolutionIssue:
    """Poll Cursor job status and copy ``pr_url`` / ``agent_url`` onto the issue.

    FL-4C.4: when ``skills.cursor_cloud.auto_create_pr`` is ``false`` the issue is
    marked ``done`` on any terminal status even without ``pr_url``; the operator is
    notified via ``pipeline_stage`` so they can open a PR manually.

    Args:
        conn (sqlite3.Connection): Workspace SQLite.
        layout (WorkspaceLayout): Workspace layout.
        issue (EvolutionIssue): Issue with ``cursor_job_id`` or ``cursor_agent_id``.
        ws (WorkspaceConfig | None): Workspace config for ``auto_create_pr`` resolution.

    Returns:
        EvolutionIssue: Updated issue row.

    Raises:
        ExecutorBlockedError: When the job row is missing.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(poll_cursor_cloud_for_issue)
        True
    """
    job: CursorCloudJob | None = None
    if issue.cursor_job_id:
        job = get_job(conn, job_id=issue.cursor_job_id)
    if job is None and issue.cursor_agent_id:
        job = get_job(conn, cursor_agent_id=issue.cursor_agent_id)
    if job is None:
        msg = f"cursor cloud job not found for issue {issue.id}"
        raise ExecutorBlockedError(msg)
    job = refresh_job_status(conn, job)
    issue.cursor_job_id = job.job_id
    issue.cursor_agent_id = job.cursor_agent_id
    issue.agent_url = job.agent_url
    issue.pr_url = job.pr_url
    issue.updated_at = utc_now_iso()
    is_terminal = job.status.upper() in _CURSOR_TERMINAL_STATUSES
    if is_terminal:
        if job.pr_url:
            issue.state = "done"
            issue.pipeline_stage = "done"
        else:
            # FL-4C.4: check whether auto_create_pr is disabled — if so, mark done
            # and append a prompt to the pipeline log so operator opens PR manually.
            auto_pr = True  # safe default: require pr_url when auto_create_pr is unknown
            if ws is not None:
                _settings, _cfg = load_cursor_cloud_settings(layout.content_root)
                auto_pr = _settings.auto_create_pr
            if not auto_pr:
                issue.state = "done"
                issue.pipeline_stage = "done"
                from sevn.evolution.pipelines import append_pipeline_log  # lazy — avoids cycle

                append_pipeline_log(
                    layout,
                    issue_id=issue.id,
                    line=(
                        f"Cursor Cloud agent finished (status={job.status}) "
                        "without a PR — auto_create_pr=false. Open the PR manually from "
                        f"{issue.agent_url or 'the Cursor dashboard'}."
                    ),
                )
    return save_issue(layout, issue)


def dispatch_cursor_cloud_implement(
    conn: sqlite3.Connection,
    ws: WorkspaceConfig,
    layout: WorkspaceLayout,
    issue_id: str,
    *,
    session_key: str = "",
    poll: bool = True,
    max_polls: int = 60,
    poll_interval_sec: float = 2.0,
) -> EvolutionIssue:
    """Launch cloud executor for an issue and optionally poll until terminal status.

    Idempotent (FL-4C.1): when the issue already has ``cursor_agent_id`` set and the
    job is non-terminal, skips ``launch_cursor_cloud_for_issue`` and polls only.
    When the job is terminal and ``pr_url`` is set the issue is marked ``done``.

    Args:
        conn (sqlite3.Connection): Workspace SQLite.
        ws (WorkspaceConfig): Parsed workspace.
        layout (WorkspaceLayout): Workspace layout.
        issue_id (str): Issue id.
        session_key (str): Optional session key for job attribution.
        poll (bool): When true, poll until terminal or ``max_polls``.
        max_polls (int): Maximum poll iterations.
        poll_interval_sec (float): Sleep between polls (seconds).

    Returns:
        EvolutionIssue: Issue after launch (and poll when enabled).

    Raises:
        ExecutorBlockedError: When issue missing or cloud path blocked.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(dispatch_cursor_cloud_implement)
        True
    """
    issue = get_issue(layout, issue_id)
    if issue is None:
        msg = f"issue not found: {issue_id}"
        raise ExecutorBlockedError(msg)
    if resolve_executor(ws, issue.kind) != "cursor_cloud":
        msg = f"executor for {issue.kind} is not cursor_cloud"
        raise ExecutorBlockedError(msg)

    # FL-4C.1 — idempotent launch: if already delegated, skip create.
    skip_launch = False
    if issue.cursor_agent_id:
        existing_job = get_job(conn, cursor_agent_id=issue.cursor_agent_id)
        if existing_job is not None:
            existing_status = existing_job.status.upper()
            if existing_status in _CURSOR_TERMINAL_STATUSES:
                # Terminal + pr_url → mark done immediately.
                if existing_job.pr_url or issue.pr_url:
                    issue.state = "done"
                    issue.pipeline_stage = "done"
                    issue.pr_url = existing_job.pr_url or issue.pr_url
                    issue.updated_at = utc_now_iso()
                    return save_issue(layout, issue)
                # Terminal but no pr_url — fall through to (re)launch below.
            else:
                # Non-terminal: poll only.
                skip_launch = True

    if not skip_launch:
        issue = launch_cursor_cloud_for_issue(
            conn,
            ws,
            layout,
            issue,
            session_key=session_key,
        )
    if not poll:
        return issue
    for _ in range(max(1, max_polls)):
        issue = poll_cursor_cloud_for_issue(conn, layout, issue)
        job = get_job(conn, job_id=issue.cursor_job_id or "")
        status = (job.status if job else "").upper()
        if status in _CURSOR_TERMINAL_STATUSES:
            break
        if poll_interval_sec > 0:
            time.sleep(poll_interval_sec)
    return issue


__all__ = [
    "ExecutorBlockedError",
    "build_cursor_cloud_prompt",
    "dispatch_cursor_cloud_implement",
    "launch_cursor_cloud_for_issue",
    "poll_cursor_cloud_for_issue",
    "resolve_executor",
    "resolve_target_repo_url",
]
