"""Cron registration for the Reddit karma loop (#74, W33.9).

Module: sevn.integrations.reddit_karma.scheduler
Depends: sqlite3, time, sevn.integrations.reddit_karma.config, sevn.triggers.cron

Exports:
    reconcile_reddit_karma_cron_job — mirror ``skills.reddit_karma_loop.enabled``.
    register_reddit_karma_cron_handler — bind cron handler at boot.
    run_reddit_karma_cron — cron entry (returns discovery plan envelope).

Constants (also in ``__all__``): ``REDDIT_KARMA_CRON_JOB_ID``.
"""

from __future__ import annotations

import sqlite3  # noqa: TC003 — runtime cron reconcile against sevn.db
import time
from pathlib import Path
from typing import Any

from sevn.config.workspace_config import WorkspaceConfig  # noqa: TC001 — cron reconcile API
from sevn.integrations.reddit_karma.config import resolve_reddit_karma_config
from sevn.integrations.reddit_karma.loop import run_draft_loop
from sevn.triggers.cron import compute_next_fire_ns, register_cron_job_handler

REDDIT_KARMA_CRON_JOB_ID = "reddit-karma-loop"
_DEFAULT_TEMPLATE = (
    "Re: {{title}} in r/{{subreddit}}\n\n"
    "{{grounding}}\n\n"
    "(Draft — operator must approve before posting; D11 draft-only.)"
)


def run_reddit_karma_cron(*, workspace: Path | None = None) -> dict[str, Any]:
    """Cron handler: plan discovery and emit structured log rows (no auto_post).

    Args:
        workspace (Path | None, optional): Workspace root; defaults to ``SEVN_WORKSPACE``.

    Returns:
        dict[str, Any]: Loop summary envelope.

    Examples:
        >>> import json, tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     ws = Path(tmp)
        ...     _ = (ws / "sevn.json").write_text(
        ...         json.dumps({"schema_version": 1, "gateway": {"token": "t"}})
        ...     )
        ...     run_reddit_karma_cron(workspace=ws)["ok"]
        True
    """
    from sevn.config.loader import load_workspace

    root = (
        workspace
        if workspace is not None
        else Path(__import__("os").environ.get("SEVN_WORKSPACE", ".")).resolve()
    )
    cfg, _layout = load_workspace(start_dir=root)
    loop_cfg = resolve_reddit_karma_config(cfg)
    if not loop_cfg.enabled:
        return {"ok": True, "skipped": "reddit_karma_loop disabled"}
    return run_draft_loop(root, cfg, candidates=None, template=_DEFAULT_TEMPLATE, dry_run=True)


def reconcile_reddit_karma_cron_job(conn: sqlite3.Connection, workspace: WorkspaceConfig) -> None:
    """Insert/update/delete the Reddit karma cron row from config.

    Args:
        conn (sqlite3.Connection): Migrated workspace ``sevn.db`` connection.
        workspace (WorkspaceConfig): Parsed workspace config source.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> reconcile_reddit_karma_cron_job(c, WorkspaceConfig.minimal())
    """
    cfg = resolve_reddit_karma_config(workspace)
    job_id = REDDIT_KARMA_CRON_JOB_ID
    if not cfg.enabled:
        conn.execute("DELETE FROM trigger_cron_jobs WHERE job_id = ?", (job_id,))
        conn.commit()
        return
    now_ns = time.time_ns()
    nxt = compute_next_fire_ns(cron_expr=cfg.cron_expr, tz_name="UTC", from_ns=now_ns)
    conn.execute(
        """
        INSERT INTO trigger_cron_jobs (
            job_id, enabled, cron_expr, timezone, next_fire_at_ns, jitter_s,
            routing_mode, delivery_mode, permission_template_ref, allow_tier_cd,
            overlap_policy, result_channel_json, payload_template
        ) VALUES (?, 1, ?, 'UTC', ?, 0, 'fixed', 'agent_pass', 'default', 0, 'skip', '{}', ?)
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
        (job_id, cfg.cron_expr, int(nxt), "reddit_karma_loop"),
    )
    conn.commit()


def _handle_reddit_karma_cron(*, workspace: Path) -> None:
    """Cron handler entry for :data:`REDDIT_KARMA_CRON_JOB_ID`.

    Args:
        workspace (Path): Workspace content root.

    Examples:
        >>> _handle_reddit_karma_cron.__name__
        '_handle_reddit_karma_cron'
    """
    run_reddit_karma_cron(workspace=workspace)


def register_reddit_karma_cron_handler() -> None:
    """Bind :data:`REDDIT_KARMA_CRON_JOB_ID` to the loop handler.

    Examples:
        >>> register_reddit_karma_cron_handler()
    """
    register_cron_job_handler(REDDIT_KARMA_CRON_JOB_ID, _handle_reddit_karma_cron)


__all__ = [
    "REDDIT_KARMA_CRON_JOB_ID",
    "reconcile_reddit_karma_cron_job",
    "register_reddit_karma_cron_handler",
    "run_reddit_karma_cron",
]
