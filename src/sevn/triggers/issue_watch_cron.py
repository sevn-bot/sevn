"""Built-in GitHub issue-watch cron scope (D13) — seed, handler, and notify path.

Module: sevn.triggers.issue_watch_cron
Depends: os, sqlite3, time, pathlib, sevn.triggers.cron, sevn.integrations.github_skill.watch

Exports:
    run_issue_watch_cron — watch tracked issues / notify on diffs.
    ensure_issue_watch_cron_job — seed the built-in watch cron row at boot.

Constants (also in ``__all__``): ``ISSUE_WATCH_CRON_JOB_ID``, ``ISSUE_WATCH_CRON_EXPR``.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from sevn.config.workspace_config import WorkspaceConfig
from sevn.triggers.cron import compute_next_fire_ns, register_cron_job_handler

# Built-in GitHub issue-watch cron job id (D13). Single SSOT — do not duplicate.
ISSUE_WATCH_CRON_JOB_ID = "gh-issue-watch"
ISSUE_WATCH_CRON_EXPR = "*/15 * * * *"


def run_issue_watch_cron(
    *,
    workspace: Path | None = None,
    diffs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Run issue watch over the tracked set, or notify precomputed ``diffs``.

    When ``diffs`` is provided (tests / manual), skip fetch and only notify.
    Otherwise load tracked issues via :mod:`sevn.integrations.github_skill.watch`
    and notify when any entry reports changes.

    Args:
        workspace (Path | None, optional): Workspace root; defaults to ``SEVN_WORKSPACE``.
        diffs (list[dict[str, Any]] | None, optional): Precomputed diffs to notify.

    Returns:
        list[dict[str, Any]]: Diffs that were (or would be) notified.

    Examples:
        >>> run_issue_watch_cron(diffs=[])
        []
    """
    from sevn.integrations.github_skill.watch import run_tracked_watch
    from sevn.triggers.dispatcher import notify_issue_watch_diff

    root = (
        workspace
        if workspace is not None
        else Path(os.environ.get("SEVN_WORKSPACE", ".")).resolve()
    )
    if diffs is not None:
        if diffs:
            notify_issue_watch_diff(diffs=diffs, content_root=root)
        return list(diffs)

    collected = run_tracked_watch(root)
    if collected:
        notify_issue_watch_diff(diffs=collected, content_root=root)
    return collected


def ensure_issue_watch_cron_job(conn: sqlite3.Connection, workspace: WorkspaceConfig) -> None:
    """Seed the built-in ``gh-issue-watch`` cron row at gateway boot (D13).

    Always ensures the job exists (~15 min). Watching is a no-op until the
    operator tracks issues under ``.sevn/gh-watch/tracked.json``.

    Args:
        conn (sqlite3.Connection): Migrated workspace ``sevn.db``.
        workspace (WorkspaceConfig): Parsed workspace (unused; reserved for gates).

    Returns:
        None

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> ensure_issue_watch_cron_job(c, WorkspaceConfig.minimal())
        >>> c.execute(
        ...     "SELECT job_id FROM trigger_cron_jobs WHERE job_id = ?",
        ...     (ISSUE_WATCH_CRON_JOB_ID,),
        ... ).fetchone()[0]
        'gh-issue-watch'
    """
    _ = workspace
    now_ns = time.time_ns()
    nxt = compute_next_fire_ns(
        cron_expr=ISSUE_WATCH_CRON_EXPR,
        tz_name="UTC",
        from_ns=now_ns,
    )
    conn.execute(
        """
        INSERT INTO trigger_cron_jobs (
            job_id, enabled, cron_expr, timezone, next_fire_at_ns, jitter_s,
            routing_mode, delivery_mode, permission_template_ref, allow_tier_cd,
            overlap_policy, result_channel_json, payload_template
        ) VALUES (?, 1, ?, 'UTC', ?, 0, 'fixed', 'notify_only', 'default', 0, 'skip', '{}', ?)
        ON CONFLICT(job_id) DO UPDATE SET
            enabled = 1,
            cron_expr = excluded.cron_expr,
            timezone = excluded.timezone,
            next_fire_at_ns = CASE
                WHEN trigger_cron_jobs.next_fire_at_ns > 0
                THEN trigger_cron_jobs.next_fire_at_ns
                ELSE excluded.next_fire_at_ns
            END,
            delivery_mode = excluded.delivery_mode,
            payload_template = excluded.payload_template
        """,
        (ISSUE_WATCH_CRON_JOB_ID, ISSUE_WATCH_CRON_EXPR, int(nxt), "gh_issue_watch"),
    )
    conn.commit()


def _handle_issue_watch_cron(*, workspace: Path) -> None:
    """Cron handler entry for :data:`ISSUE_WATCH_CRON_JOB_ID`.

    Args:
        workspace (Path): Workspace content root.

    Returns:
        None

    Examples:
        >>> _handle_issue_watch_cron.__name__
        '_handle_issue_watch_cron'
    """
    run_issue_watch_cron(workspace=workspace)


register_cron_job_handler(ISSUE_WATCH_CRON_JOB_ID, _handle_issue_watch_cron)


__all__ = [
    "ISSUE_WATCH_CRON_EXPR",
    "ISSUE_WATCH_CRON_JOB_ID",
    "ensure_issue_watch_cron_job",
    "run_issue_watch_cron",
]
