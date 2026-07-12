"""Auto-start evolution pipeline on issue import (`plan/dev_eval_14062026/evolution-auto-run-import-wave-plan.md` AR-1).

When ``my_sevn.issues.auto_run_on_import`` is ``true`` and a GitHub issue is **newly**
imported (``created=True``), this module schedules :func:`run_pipeline` in the background
via :func:`spawn_logged`.  Dry-run flags are left ``None`` so they resolve from
``my_sevn.pipelines`` config defaults — D3 decision in the wave plan.

``PipelineBlockedError`` is swallowed: feature issues that require approval stop at the
HITL gate and that is the expected operator experience (D5).

Module: sevn.evolution.pipeline_autostart
Depends: sevn.config.my_sevn, sevn.evolution.pipeline_common, sevn.evolution.pipeline_runner,
    sevn.runtime.background_tasks

Exports:
    maybe_auto_run_pipeline_after_import — schedule run_pipeline when auto_run_on_import is enabled.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from sevn.config.my_sevn import effective_my_sevn_issues
from sevn.evolution.pipeline_common import PipelineBlockedError
from sevn.runtime.background_tasks import spawn_logged

if TYPE_CHECKING:
    import sqlite3

    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.evolution.events import EvolutionIssueEventFanoutFn
    from sevn.evolution.issues import EvolutionIssue
    from sevn.workspace.layout import WorkspaceLayout


def maybe_auto_run_pipeline_after_import(
    layout: WorkspaceLayout,
    ws: WorkspaceConfig,
    conn: sqlite3.Connection,
    issue: EvolutionIssue,
    *,
    created: bool,
    fanout: EvolutionIssueEventFanoutFn | None = None,
) -> bool:
    """Schedule ``run_pipeline`` for a newly-imported issue when auto-run is enabled.

    Guards (all must pass before scheduling):

    * ``my_sevn.issues.auto_run_on_import`` must be ``true``.
    * ``created`` must be ``True`` — re-imports of existing issues are no-ops (D2).
    * ``issue.state`` must be ``"open"`` — terminal/cancelled issues are skipped.
    * ``issue.pipeline_stage`` must not be ``"awaiting_approval"`` — HITL blocks (D5).

    When scheduled, ``PipelineBlockedError`` raised inside the background task is
    caught and logged as an informational message rather than an error; this is the
    expected path for feature issues with ``require_approval=true``.

    Args:
        layout (WorkspaceLayout): Workspace layout for the local issue store.
        ws (WorkspaceConfig): Workspace config with ``auto_run_on_import`` flag.
        conn (sqlite3.Connection): SQLite connection forwarded to ``run_pipeline``.
        issue (EvolutionIssue): Issue record returned by the import call.
        created (bool): ``True`` when the import created a new record, not an update.
        fanout (EvolutionIssueEventFanoutFn | None, optional): Event fanout for gateway
            subscribers; forwarded verbatim to ``run_pipeline``.

    Returns:
        bool: ``True`` when ``run_pipeline`` was scheduled, ``False`` when any guard
            failed and the issue was intentionally skipped.

    Examples:
        >>> maybe_auto_run_pipeline_after_import.__name__
        'maybe_auto_run_pipeline_after_import'
    """
    if not effective_my_sevn_issues(ws).auto_run_on_import:
        return False
    if not created:
        return False
    if issue.state != "open":
        return False
    if (issue.pipeline_stage or "") == "awaiting_approval":
        return False

    from sevn.evolution.pipeline_runner import run_pipeline

    issue_id = issue.id
    logger.info("evolution.auto_run_scheduled issue_id={}", issue_id)

    async def _run() -> None:
        try:
            await run_pipeline(conn, ws, layout, issue_id, fanout=fanout)
        except PipelineBlockedError:
            logger.info(
                "evolution.auto_run_blocked issue_id={} — HITL gate, no retry needed",
                issue_id,
            )

    spawn_logged(_run(), label=f"auto_run:{issue_id}")
    return True


__all__ = ["maybe_auto_run_pipeline_after_import"]
