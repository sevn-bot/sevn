"""Cron registration against ``trigger_cron_jobs`` (`specs/30-non-interactive-triggers.md` §3.2).

Module: sevn.memory.dreaming.scheduler
Depends: sqlite3, sevn.config.workspace_config

Exports:
    effective_dreaming — resolve typed Dreaming block with defaults.
    reconcile_dreaming_cron_job — mirror ``memory.dreaming.enabled`` into SQLite.
"""

from __future__ import annotations

import sqlite3
import time

from sevn.config.workspace_config import DreamingWorkspaceConfig, WorkspaceConfig
from sevn.memory.dreaming.defaults import DREAMING_CRON_JOB_ID
from sevn.triggers.cron import compute_next_fire_ns


def effective_dreaming(ws: WorkspaceConfig) -> DreamingWorkspaceConfig:
    """Return ``DreamingWorkspaceConfig`` with defaults when subtree absent.

    Args:
        ws (WorkspaceConfig): Parsed workspace root model.

    Returns:
        DreamingWorkspaceConfig: Effective Dreaming configuration object.

    Examples:
        >>> effective_dreaming(WorkspaceConfig.minimal()).enabled
        True
    """
    if ws.memory and ws.memory.dreaming:
        return ws.memory.dreaming
    return DreamingWorkspaceConfig()


def reconcile_dreaming_cron_job(conn: sqlite3.Connection, ws: WorkspaceConfig) -> None:
    """Insert/update/delete the Dreaming cron row mirroring ``memory.dreaming.enabled``.

    Args:
        conn (sqlite3.Connection): Shared ``sevn.db`` connection (commits internally).
        ws (WorkspaceConfig): Workspace configuration source.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> reconcile_dreaming_cron_job(c, WorkspaceConfig.minimal())
        >>> int(c.execute("SELECT COUNT(*) FROM trigger_cron_jobs").fetchone()[0])
        1
        >>> c.close()
    """
    cfg = effective_dreaming(ws)
    job_id = DREAMING_CRON_JOB_ID
    if not cfg.enabled:
        conn.execute("DELETE FROM trigger_cron_jobs WHERE job_id = ?", (job_id,))
        conn.commit()
        return
    now_ns = time.time_ns()
    nxt = compute_next_fire_ns(cron_expr=cfg.cron, tz_name="UTC", from_ns=now_ns)
    conn.execute(
        """
        INSERT INTO trigger_cron_jobs (
            job_id, enabled, cron_expr, timezone, next_fire_at_ns, jitter_s,
            routing_mode, delivery_mode, permission_template_ref, allow_tier_cd,
            overlap_policy, result_channel_json, payload_template
        ) VALUES (?, 1, ?, 'UTC', ?, 0, 'fixed', 'notify_only', 'default', 0, 'skip', '{}', ?)
        ON CONFLICT(job_id) DO UPDATE SET
            enabled = excluded.enabled,
            cron_expr = excluded.cron_expr,
            timezone = excluded.timezone,
            next_fire_at_ns = excluded.next_fire_at_ns,
            routing_mode = excluded.routing_mode,
            delivery_mode = excluded.delivery_mode,
            permission_template_ref = excluded.permission_template_ref,
            allow_tier_cd = excluded.allow_tier_cd,
            overlap_policy = excluded.overlap_policy,
            result_channel_json = excluded.result_channel_json,
            payload_template = excluded.payload_template
        """,
        (job_id, cfg.cron, int(nxt), "sevn_memory_dreaming"),
    )
    conn.commit()
