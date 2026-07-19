"""Daily ``sevn sync`` cron registration (`specs/35-bot-evolution.md`, `specs/30-non-interactive-triggers.md`).

Module: sevn.evolution.repo_sync_scheduler
Depends: sevn.cli.repo_sync, sevn.config.my_sevn, sevn.config.workspace_config, sevn.triggers.cron

Exports:
    reconcile_my_sevn_sync_cron_job — mirror ``my_sevn.sync.enabled`` into SQLite.
    reconcile_my_sevn_issues_sync_cron_job — mirror ``my_sevn.issues.sync_enabled`` into SQLite.
    run_scheduled_repo_sync — fetch and fast-forward the source checkout.
    run_scheduled_repo_sync_with_recovery — cron-owned divergence auto-recovers with ``--latest``.
    run_scheduled_issues_sync — import GitHub issues into the local registry.
    sync_source_tree — lazy delegate to ``sevn.cli.repo_sync.sync_source_tree``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from loguru import logger

from sevn.config.defaults import DEFAULT_MY_SEVN_ISSUES_SYNC_CRON, DEFAULT_MY_SEVN_SYNC_CRON
from sevn.config.my_sevn import effective_my_sevn_issues, effective_my_sevn_sync
from sevn.triggers.cron import compute_next_fire_ns

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from sevn.cli.repo_sync import RepoSyncError
    from sevn.cli.repo_sync import SyncResult as RepoSyncResult
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.evolution.github_sync import SyncResult
    from sevn.workspace.layout import WorkspaceLayout

MY_SEVN_SYNC_CRON_JOB_ID: str = "sevn_my_sevn_repo_sync"
MY_SEVN_ISSUES_SYNC_CRON_JOB_ID: str = "sevn_my_sevn_issues_sync"


def sync_source_tree(
    *,
    repo_root: Path,
    latest: bool = False,
    dry_run: bool = False,
    restart_gateway: bool = True,
    home: Path | None = None,
) -> RepoSyncResult:
    """Lazy delegate to :func:`sevn.cli.repo_sync.sync_source_tree` (monkeypatch-friendly).

    Args:
        repo_root (Path): sevn.bot checkout root.
        latest (bool): Force sync to the remote tip.
        dry_run (bool): Plan without mutating disk or services.
        restart_gateway (bool): Restart gateway when its user unit is active.
        home (Path | None): Operator home for service control.

    Returns:
        RepoSyncResult: Sync outcome from the checkout update.

    Examples:
        >>> sync_source_tree.__name__
        'sync_source_tree'
    """
    from sevn.cli.repo_sync import sync_source_tree as _sync_source_tree

    return _sync_source_tree(
        repo_root=repo_root,
        latest=latest,
        dry_run=dry_run,
        restart_gateway=restart_gateway,
        home=home,
    )


def _resolve_sync_repo_root(*, home: Path | None = None) -> Path:
    """Resolve checkout for scheduled sync from ``sevn.json`` then CLI fallbacks.

    Args:
        home (Path | None): Reserved (sync uses bound workspace via ``SEVN_HOME``).

    Returns:
        Path: Absolute sevn.bot checkout root.

    Raises:
        RepoSyncError: When no checkout can be resolved.

    Examples:
        >>> _resolve_sync_repo_root.__name__
        '_resolve_sync_repo_root'
    """
    from sevn.cli.errors import CliPreconditionError
    from sevn.cli.repo_sync import RepoSyncError
    from sevn.cli.workspace import load_bound_workspace
    from sevn.config.sevn_repo import resolve_sevn_checkout_for_workspace

    _ = home
    try:
        bw = load_bound_workspace()
        configured = resolve_sevn_checkout_for_workspace(
            bw.config,
            content_root=bw.layout.content_root,
        )
        if configured is not None:
            return configured
    except (CliPreconditionError, OSError, ValueError):
        pass
    try:
        from sevn.cli.repo_sync import resolve_sevn_repo_root

        return resolve_sevn_repo_root()
    except Exception as exc:
        msg = (
            "could not find sevn.bot source checkout "
            "(set my_sevn.repo_path in sevn.json or run from inside the repository)"
        )
        raise RepoSyncError(msg) from exc


def reconcile_my_sevn_sync_cron_job(conn: sqlite3.Connection, ws: WorkspaceConfig) -> None:
    """Insert/update/delete the daily repo-sync cron row mirroring ``my_sevn.sync.enabled``.

    Args:
        conn (sqlite3.Connection): Shared ``sevn.db`` connection (commits internally).
        ws (WorkspaceConfig): Workspace configuration source.

    Examples:
        >>> import sqlite3
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> reconcile_my_sevn_sync_cron_job(c, WorkspaceConfig.minimal())
        >>> int(c.execute("SELECT COUNT(*) FROM trigger_cron_jobs").fetchone()[0])
        1
        >>> c.close()
    """
    sync_cfg = effective_my_sevn_sync(ws)
    job_id = MY_SEVN_SYNC_CRON_JOB_ID
    if not sync_cfg.enabled:
        conn.execute("DELETE FROM trigger_cron_jobs WHERE job_id = ?", (job_id,))
        conn.commit()
        return
    cron_expr = sync_cfg.cron.strip() or DEFAULT_MY_SEVN_SYNC_CRON
    now_ns = time.time_ns()
    nxt = compute_next_fire_ns(cron_expr=cron_expr, tz_name="UTC", from_ns=now_ns)
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
        (job_id, cron_expr, int(nxt), MY_SEVN_SYNC_CRON_JOB_ID),
    )
    conn.commit()


def reconcile_my_sevn_issues_sync_cron_job(conn: sqlite3.Connection, ws: WorkspaceConfig) -> None:
    """Insert/update/delete the issues-sync cron row mirroring ``my_sevn.issues.sync_enabled``.

    Registered beside :func:`reconcile_my_sevn_sync_cron_job`; fires at
    ``my_sevn.issues.sync_cron`` (default ``0 */6 * * *``) to import GitHub issues.

    Args:
        conn (sqlite3.Connection): Shared ``sevn.db`` connection (commits internally).
        ws (WorkspaceConfig): Workspace configuration source.

    Examples:
        >>> import sqlite3
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> reconcile_my_sevn_issues_sync_cron_job(c, WorkspaceConfig.minimal())
        >>> int(
        ...     c.execute(
        ...         "SELECT COUNT(*) FROM trigger_cron_jobs WHERE job_id = ?",
        ...         ("sevn_my_sevn_issues_sync",),
        ...     ).fetchone()[0]
        ... )
        1
        >>> c.close()
    """
    issues_cfg = effective_my_sevn_issues(ws)
    job_id = MY_SEVN_ISSUES_SYNC_CRON_JOB_ID
    if not issues_cfg.sync_enabled:
        conn.execute("DELETE FROM trigger_cron_jobs WHERE job_id = ?", (job_id,))
        conn.commit()
        return
    cron_expr = issues_cfg.sync_cron.strip() or DEFAULT_MY_SEVN_ISSUES_SYNC_CRON
    now_ns = time.time_ns()
    nxt = compute_next_fire_ns(cron_expr=cron_expr, tz_name="UTC", from_ns=now_ns)
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
        (job_id, cron_expr, int(nxt), MY_SEVN_ISSUES_SYNC_CRON_JOB_ID),
    )
    conn.commit()


async def run_scheduled_issues_sync(layout: WorkspaceLayout, ws: WorkspaceConfig) -> SyncResult:
    """Import GitHub issues into the local registry for the configured repo.

    Args:
        layout (WorkspaceLayout): Workspace layout for the local issue store.
        ws (WorkspaceConfig): Workspace config supplying repo slug and label map.

    Returns:
        SyncResult: Import/update/skip counters.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_scheduled_issues_sync)
        True
    """
    from sevn.evolution.github_sync import sync_github_issues
    from sevn.evolution.issues import my_sevn_repo_slug
    from sevn.integrations.github_skill import resolve_github_skill_hooks

    hooks = resolve_github_skill_hooks(ws)
    result = await sync_github_issues(
        layout,
        hooks,
        repo=my_sevn_repo_slug(ws),
        ws=ws,
    )
    logger.info(
        "my_sevn_issues_sync imported={} updated={} skipped={}",
        result.imported,
        result.updated,
        result.skipped,
    )
    return result


def _repo_sync_error_is_diverged(exc: RepoSyncError) -> bool:
    """Return True when ``exc`` is the expected fast-forward refusal on a diverged tip.

    Args:
        exc (RepoSyncError): Failure from :func:`run_scheduled_repo_sync` / ``sync_source_tree``.

    Returns:
        bool: True when the message indicates diverged local history.

    Examples:
        >>> from sevn.cli.repo_sync import RepoSyncError
        >>> _repo_sync_error_is_diverged(RepoSyncError("local history diverged from origin/x"))
        True
        >>> _repo_sync_error_is_diverged(RepoSyncError("git fetch failed"))
        False
    """
    return "diverged" in str(exc).casefold()


def run_scheduled_repo_sync_with_recovery(
    *, home: Path | None = None, dry_run: bool = False
) -> str:
    """Run scheduled sync; on cron-owned divergence reset to remote with ``--latest``.

    The daily cron owns the configured ``my_sevn.repo_path`` checkout, so a refused
    ``--ff-only`` sync is auto-recovered once per run instead of failing every morning.
    Non-divergence failures propagate unchanged.

    Args:
        home (Path | None): Operator home for optional gateway restart.
        dry_run (bool): Plan sync steps without mutating disk or services.

    Returns:
        str: Human-readable outcome for logs.

    Raises:
        RepoSyncError: When sync fails for reasons other than recoverable divergence.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(run_scheduled_repo_sync_with_recovery)
        True
    """
    from sevn.cli.repo_sync import RepoSyncError

    try:
        return run_scheduled_repo_sync(home=home, dry_run=dry_run)
    except RepoSyncError as exc:
        if not _repo_sync_error_is_diverged(exc):
            raise
        logger.warning(
            "my_sevn repo sync cron: local checkout diverged from tracking branch; "
            "auto-recovering with --latest (run `sevn sync --latest` manually if needed)",
        )
        repo_root = _resolve_sync_repo_root(home=home)
        result = sync_source_tree(
            repo_root=repo_root,
            latest=True,
            dry_run=dry_run,
            restart_gateway=not dry_run,
            home=home,
        )
        detail = result.detail
        if not dry_run:
            logger.info(
                "my_sevn_repo_sync recovered after divergence updated={} local={} remote={} detail={}",
                result.updated,
                result.local_rev[:12],
                result.remote_rev[:12],
                detail,
            )
        return detail


def run_scheduled_repo_sync(*, home: Path | None = None, dry_run: bool = False) -> str:
    """Run ``sync_source_tree`` for the resolved sevn.bot checkout.

    Args:
        home (Path | None): Operator home for optional gateway restart.
        dry_run (bool): Plan sync steps without ``git fetch`` or gateway restart.

    Returns:
        str: Human-readable outcome for logs.

    Raises:
        RepoSyncError: When the checkout cannot be resolved or git fails.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(run_scheduled_repo_sync)
        True
    """
    repo_root = _resolve_sync_repo_root(home=home)
    result = sync_source_tree(
        repo_root=repo_root,
        latest=False,
        dry_run=dry_run,
        restart_gateway=not dry_run,
        home=home,
    )
    detail = result.detail
    logger.info(
        "my_sevn_repo_sync updated={} local={} remote={} detail={}",
        result.updated,
        result.local_rev[:12],
        result.remote_rev[:12],
        detail,
    )
    return detail


__all__ = [
    "MY_SEVN_ISSUES_SYNC_CRON_JOB_ID",
    "MY_SEVN_SYNC_CRON_JOB_ID",
    "reconcile_my_sevn_issues_sync_cron_job",
    "reconcile_my_sevn_sync_cron_job",
    "run_scheduled_issues_sync",
    "run_scheduled_repo_sync",
    "run_scheduled_repo_sync_with_recovery",
    "sync_source_tree",
]
