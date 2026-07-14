"""Gateway hook registration for trajectory ingest (Batch C lane #3).

Module: sevn.gateway.hooks.trajectory_ingest_hooks
Depends: sevn.gateway.boot_registry, sevn.gateway.hooks.post_turn_hooks

Exports:
    register_trajectory_ingest_hooks — register post-turn, cron, and dispatch hooks.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from sevn.gateway.boot_registry import BootContext, register_boot_hook, register_cron_job
from sevn.gateway.hooks.post_turn_hooks import PostTurnContext, register_post_turn_hook
from sevn.self_improve.trajectories.queue import schedule_trajectory_ingest
from sevn.self_improve.trajectories.runner import run_trajectory_ingest
from sevn.self_improve.trajectories.scheduler import (
    TRAJECTORY_INGEST_CRON_JOB_ID,
    effective_trajectories,
    reconcile_trajectory_ingest_cron_job,
    run_scheduled_trajectory_ingest,
)
from sevn.storage.paths import traces_sqlite_path


async def _post_turn_trajectory_ingest(ctx: PostTurnContext) -> None:
    """Schedule debounced per-turn trajectory ingest after gateway completion.

    Args:
        ctx (PostTurnContext): Turn-end state from ``run_post_turn_hooks``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_post_turn_trajectory_ingest)
        True
    """
    router = ctx.router
    content_root = getattr(router, "_content_root", None)
    workspace = getattr(router, "_workspace", None)
    if content_root is None or workspace is None:
        return
    cfg = effective_trajectories(workspace)
    if not cfg.ingest_on_turn:
        return
    from sevn.workspace.layout import WorkspaceLayout

    layout = WorkspaceLayout(
        sevn_json_path=content_root / "sevn.json",
        content_root=content_root,
    )
    traces_path = traces_sqlite_path(layout.dot_sevn)
    if not traces_path.is_file():
        return
    workspace_key = str(layout.content_root)

    async def _job() -> None:
        run_trajectory_ingest(ctx.conn, layout, turn_id=ctx.correlation_id)

    await schedule_trajectory_ingest(workspace_key, ctx.correlation_id, _job)


async def _wrap_dispatch_for_trajectory_ingest(ctx: BootContext) -> None:
    """Wrap ``dispatch_trigger`` so cron fires incremental trajectory backfill.

    Args:
        ctx (BootContext): Lifespan startup context.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_wrap_dispatch_for_trajectory_ingest)
        True
    """
    original = getattr(ctx.app.state, "dispatch_trigger", None)
    if original is None:
        return

    async def wrapped(req: Any) -> None:
        if (
            req.trigger_meta.get("transport") == "cron"
            and req.trigger_meta.get("cron_job_id") == TRAJECTORY_INGEST_CRON_JOB_ID
        ):
            st = ctx.app.state
            try:
                await asyncio.to_thread(
                    run_scheduled_trajectory_ingest,
                    st.sqlite_conn,
                    st.layout,
                    st.workspace,
                )
            except Exception:
                logger.exception("trajectory_ingest_cron_dispatch_failed")
            return
        await original(req)

    ctx.app.state.dispatch_trigger = wrapped


def register_trajectory_ingest_hooks() -> None:
    """Register trajectory ingest hooks via CW-1 / CW-2 registries.

    Examples:
        >>> "register_trajectory_ingest_hooks" in __all__
        True
    """
    register_post_turn_hook("trajectory_ingest", _post_turn_trajectory_ingest, priority=30)
    register_cron_job("trajectory_ingest", reconcile_trajectory_ingest_cron_job, priority=5)
    register_boot_hook(
        "trajectory_ingest_dispatch", _wrap_dispatch_for_trajectory_ingest, priority=60
    )


register_trajectory_ingest_hooks()

__all__ = ["register_trajectory_ingest_hooks"]
