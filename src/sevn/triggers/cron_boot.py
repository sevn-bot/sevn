"""Gateway boot hook for cron audit stale-claim recovery (#85).

Module: sevn.triggers.cron_boot
Depends: sevn.gateway.boot_registry, sevn.triggers.cron_runs

Exports:
    reconcile_stale_cron_claims — boot reconcile hook for stale cron audit rows.
"""

from __future__ import annotations

import sqlite3
import time

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.boot_registry import register_cron_job
from sevn.triggers.cron_runs import recover_stale_cron_claims


def reconcile_stale_cron_claims(
    conn: sqlite3.Connection,
    _workspace: WorkspaceConfig,
) -> None:
    """Mark in-flight cron audit rows stale during gateway boot reconcile.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        _workspace (WorkspaceConfig): Active workspace config (unused).

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.triggers.cron_boot import reconcile_stale_cron_claims
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> reconcile_stale_cron_claims(c, WorkspaceConfig.minimal())
    """
    recover_stale_cron_claims(conn, now_ns=time.time_ns())


register_cron_job("cron_stale_claims", reconcile_stale_cron_claims, priority=5)
