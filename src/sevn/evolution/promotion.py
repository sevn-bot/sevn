"""Promotion step — push + open PR + persist ``pr_url`` (`specs/35-bot-evolution.md` FL-3).

``promote_issue`` is the single async promotion entry-point for local-executor
evolution issues.  It:

1. Pre-checks that the worktree has commits ahead of the base — aborts with a clear
   ``PromotionError`` if there is nothing to promote.
2. Pushes the branch to origin (reuses the ``git push -u origin <branch>`` pattern
   from :func:`worktree.promote_worktree`).
3. Opens a pull request via :func:`gh_pr.create_pull_request` unless
   ``promotion_dry_run`` is ``True``.
4. Persists ``issue.pr_url``, appends a pipeline log line, and advances the stage to
   ``promote/done``.

The function is *async* because ``gh_pr.create_pull_request`` is async.

Module: sevn.evolution.promotion
Depends: sevn.evolution.issues, sevn.evolution.pipeline_common,
    sevn.evolution.pipelines, sevn.evolution.worktree,
    sevn.integrations.github_skill.gh_pr, sevn.integrations.github_skill.hooks

Exports:
    PromotionError — worktree/push/PR failure.
    promote_issue — pre-check → push → PR → persist.

Private:
    _commits_ahead — count commits in worktree ahead of base.
    _build_pr_body — compose PR body with issue and artefact links.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404
from typing import TYPE_CHECKING

from loguru import logger

from sevn.evolution.pipeline_common import set_issue_stage
from sevn.evolution.pipelines import append_pipeline_log
from sevn.evolution.worktree import WorktreeError, load_worktree_lease
from sevn.integrations.github_skill.gh_pr import create_pull_request

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.evolution.issues import EvolutionIssue
    from sevn.integrations.github_skill.hooks import GithubSkillHooks
    from sevn.workspace.layout import WorkspaceLayout


class PromotionError(RuntimeError):
    """Raised when promotion cannot proceed (no commits, push failure, PR error)."""


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one git subprocess in *cwd*.

    Args:
        cwd (Path): Repository or worktree root.
        args (str): Git subcommand and arguments (variadic).

    Returns:
        subprocess.CompletedProcess[str]: Completed process.

    Examples:
        >>> _git.__name__
        '_git'
    """
    git_bin = shutil.which("git") or "git"
    return subprocess.run(  # nosec B603 — fixed git argv; no shell
        [git_bin, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _commits_ahead(checkout: Path, base_sha: str) -> int:
    """Return the number of commits in *checkout* that are ahead of *base_sha*.

    Args:
        checkout (Path): Worktree checkout directory.
        base_sha (str): Base commit SHA (from the lease).

    Returns:
        int: Commit count ahead; ``0`` when the worktree matches the base or
        git fails.

    Examples:
        >>> _commits_ahead.__name__
        '_commits_ahead'
    """
    proc = _git(checkout, "rev-list", "--count", f"{base_sha}..HEAD")
    if proc.returncode != 0:
        return 0
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return 0


def _dirty_files(checkout: Path) -> list[str]:
    """Return unstaged/uncommitted file paths from ``git status --porcelain``.

    Args:
        checkout (Path): Worktree checkout directory.

    Returns:
        list[str]: Dirty paths; empty list when clean or git fails.

    Examples:
        >>> _dirty_files.__name__
        '_dirty_files'
    """
    proc = _git(checkout, "status", "--porcelain")
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _build_pr_body(issue: EvolutionIssue, layout: WorkspaceLayout) -> str:
    """Compose a pull request body linking the issue and spec-kit artefacts.

    Args:
        issue (EvolutionIssue): Issue being promoted.
        layout (WorkspaceLayout): Workspace layout (used to locate artefacts).

    Returns:
        str: Markdown PR body.

    Examples:
        >>> _build_pr_body.__name__
        '_build_pr_body'
    """
    lines: list[str] = [
        f"## Evolution issue: {issue.title}",
        "",
        f"**Issue id:** `{issue.id}`",
        f"**Kind:** {issue.kind}",
    ]

    # Link GitHub issue when available.
    if issue.github:
        gh_number = issue.github.get("number")
        gh_url = issue.github.get("url") or ""
        if gh_url:
            lines.append(f"**GitHub issue:** [{gh_number}]({gh_url})")
        elif gh_number:
            lines.append(f"**GitHub issue:** #{gh_number}")

    if issue.body:
        lines += ["", "### Description", "", issue.body.strip()]

    # Spec-kit artefacts — include paths if they exist on disk.
    features_dir = layout.dot_sevn / "features" / issue.id
    artefact_names = ("spec.md", "plan.md", "tasks.md")
    existing_artefacts = [
        features_dir / name for name in artefact_names if (features_dir / name).is_file()
    ]
    if existing_artefacts:
        lines += ["", "### Spec-kit artefacts", ""]
        for artefact in existing_artefacts:
            lines.append(f"- `{artefact.relative_to(layout.dot_sevn.parent)}`")

    lines += ["", "---", "_Opened automatically by sevn.bot evolution pipeline (FL-3)._"]
    return "\n".join(lines)


async def promote_issue(
    layout: WorkspaceLayout,
    issue: EvolutionIssue,
    *,
    hooks: GithubSkillHooks,
    repo: str,
    base: str = "main",
    promotion_dry_run: bool = False,
) -> EvolutionIssue:
    """Pre-check → push → open PR → persist ``pr_url`` on the issue.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        issue (EvolutionIssue): Issue to promote; mutated and persisted in place.
        hooks (GithubSkillHooks): GitHub integration delegate.
        repo (str): ``owner/repo`` slug.
        base (str): Base branch for the PR. Defaults to ``"main"``.
        promotion_dry_run (bool): When ``True``, skip push and PR; log a
            plan-only message and advance the stage to ``promote/done``.

    Returns:
        EvolutionIssue: Persisted issue with ``pr_url`` set (or dry-run note).

    Raises:
        PromotionError: When the worktree has no commits ahead of base, the push
            fails, or the PR creation call raises.
        WorktreeError: When the worktree lease or checkout is missing.

    Examples:
        >>> promote_issue.__name__
        'promote_issue'
    """
    issue_id = issue.id

    # --- Load lease + checkout ---
    lease = load_worktree_lease(layout, issue_id)
    if lease is None:
        msg = f"promote_issue: no worktree lease for issue {issue_id}"
        raise WorktreeError(msg)

    from pathlib import Path

    checkout = Path(lease.path)
    if not os.path.isdir(checkout):  # noqa: ASYNC240 — pre-check before git subprocess
        msg = f"promote_issue: worktree checkout missing: {checkout}"
        raise WorktreeError(msg)

    branch = lease.branch or f"evolution/{issue_id}"

    # --- Dry-run path ---
    if promotion_dry_run:
        detail = f"promotion_dry_run=True: would push {branch} and open PR against {base}"
        logger.info(f"promote_issue: {detail}")
        append_pipeline_log(layout, issue_id=issue_id, line=detail)
        return set_issue_stage(
            layout,
            issue,
            state="done",
            pipeline_stage="promote/done",
            log_line="Promotion dry-run complete.",
        )

    # --- Pre-check: must have commits ahead of base ---
    ahead = _commits_ahead(checkout, lease.base_sha)
    if ahead == 0:
        dirty = _dirty_files(checkout)
        hint = f" (worktree has {len(dirty)} unstaged file(s))" if dirty else ""
        msg = (
            f"promote_issue: worktree for {issue_id} has no commits ahead of "
            f"base {lease.base_sha[:8]}{hint}; nothing to promote"
        )
        logger.warning(msg)
        append_pipeline_log(layout, issue_id=issue_id, line=msg)
        raise PromotionError(msg)

    logger.info(f"promote_issue: {issue_id} has {ahead} commit(s) ahead — proceeding")

    # --- Push ---
    push_proc = _git(checkout, "push", "-u", "origin", branch)
    if push_proc.returncode != 0:
        detail = (push_proc.stderr or push_proc.stdout or "git push failed").strip()
        full_msg = f"promote_issue: push failed for {branch}: {detail}"
        append_pipeline_log(layout, issue_id=issue_id, line=full_msg)
        raise PromotionError(full_msg)

    logger.info(f"promote_issue: pushed {branch} to origin")
    append_pipeline_log(layout, issue_id=issue_id, line=f"Pushed branch {branch} to origin.")

    # --- Open PR ---
    pr_title = f"[evolution/{issue.kind}] {issue.title}"
    pr_body = _build_pr_body(issue, layout)

    try:
        result = await create_pull_request(
            hooks,
            repo=repo,
            title=pr_title,
            body=pr_body,
            head=branch,
            base=base,
        )
    except Exception as exc:
        msg = f"promote_issue: create_pull_request raised: {exc}"
        append_pipeline_log(layout, issue_id=issue_id, line=msg)
        raise PromotionError(msg) from exc

    pr_data = result.get("pull_request") or {}
    pr_url: str = str(pr_data.get("html_url") or pr_data.get("url") or "")
    pr_number = pr_data.get("number")

    log_line = f"PR opened: {pr_url}" if pr_url else f"PR #{pr_number} opened (url not returned)"
    logger.info(f"promote_issue: {log_line}")

    # --- Persist ---
    issue.pr_url = pr_url or None
    append_pipeline_log(layout, issue_id=issue_id, line=log_line)
    return set_issue_stage(
        layout,
        issue,
        state="done",
        pipeline_stage="promote/done",
        log_line=f"Pipeline runner: promoted, pr_url={pr_url or pr_number}.",
    )


__all__ = [
    "PromotionError",
    "promote_issue",
]
