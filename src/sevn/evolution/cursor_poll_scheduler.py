"""Background 60-second poller for Cursor Cloud evolution issues (`specs/35-bot-evolution.md` FL-4C.3).

Every 60 s the scheduler scans issues where ``state=implementing``,
``executor=cursor_cloud``, and ``cursor_job_id`` is set, calls
:func:`~sevn.evolution.router.poll_cursor_cloud_for_issue` for each, then fans
the result to :class:`~sevn.gateway.evolution_issue_events.EvolutionIssueEventFanout`.

The scheduler runs only when ``my_sevn.executors.cursor_poll_mode`` is
``"background"`` (default); in ``"inline"`` or ``"manual"`` modes it is a no-op.

Module: sevn.evolution.cursor_poll_scheduler
Depends: asyncio, loguru, sevn.config.my_sevn, sevn.evolution.issues,
    sevn.evolution.router, sevn.evolution.pipelines

Exports:
    CursorPollScheduler — background worker; register via gateway lifespan.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING

from loguru import logger

from sevn.config.my_sevn import effective_my_sevn_executors
from sevn.evolution.issues import list_issues
from sevn.evolution.router import (
    ExecutorBlockedError,
    poll_cursor_cloud_for_issue,
)

if TYPE_CHECKING:
    import sqlite3

    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.evolution.events import EvolutionIssueEventFanoutFn
    from sevn.workspace.layout import WorkspaceLayout

_POLL_INTERVAL_S: float = 60.0


class CursorPollScheduler:
    """Background asyncio worker that polls Cursor Cloud issues every 60 s.

    Registration (gateway lifespan)::

        scheduler = CursorPollScheduler(
            sqlite_conn=conn,
            workspace_config=ws,
            layout=ly,
            fanout=app.state.evolution_issue_event_fanout,
        )
        await scheduler.start()
        # … at shutdown:
        await scheduler.stop()
    """

    def __init__(
        self,
        *,
        sqlite_conn: sqlite3.Connection,
        workspace_config: WorkspaceConfig,
        layout: WorkspaceLayout,
        fanout: EvolutionIssueEventFanoutFn | None = None,
        poll_interval_s: float = _POLL_INTERVAL_S,
    ) -> None:
        """Bind runtime dependencies.

        Args:
            sqlite_conn (sqlite3.Connection): Shared workspace DB connection.
            workspace_config (WorkspaceConfig): Parsed ``sevn.json``.
            layout (WorkspaceLayout): Workspace filesystem layout.
            fanout (EvolutionIssueEventFanoutFn | None): Optional event publisher for
                ``evolution.issue.*`` topics; ``None`` silently skips fan-out.
            poll_interval_s (float): Cadence between sweeps (default 60 s).

        Examples:
            >>> import sqlite3
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import WorkspaceConfig
            >>> from sevn.storage.migrate import apply_migrations
            >>> from sevn.workspace.layout import WorkspaceLayout
            >>> conn = sqlite3.connect(":memory:")
            >>> apply_migrations(conn)
            >>> ly = WorkspaceLayout(Path("/tmp/x/sevn.json"), Path("/tmp/x"))
            >>> ws = WorkspaceConfig.minimal()
            >>> sched = CursorPollScheduler(
            ...     sqlite_conn=conn,
            ...     workspace_config=ws,
            ...     layout=ly,
            ... )
            >>> sched._poll_interval_s
            60.0
            >>> conn.close()
        """
        self._conn = sqlite_conn
        self._ws = workspace_config
        self._layout = layout
        self._fanout = fanout
        self._poll_interval_s = poll_interval_s
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the background polling loop.

        No-op when ``cursor_poll_mode != "background"``.

        Returns:
            None: Side-effect only.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CursorPollScheduler.start)
            True
        """
        mode = effective_my_sevn_executors(self._ws).cursor_poll_mode
        if mode != "background":
            logger.debug("cursor_poll_scheduler: mode={} — skipping start", mode)
            return
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("cursor_poll_scheduler: started (interval={}s)", self._poll_interval_s)

    async def stop(self) -> None:
        """Cancel and join the background loop.

        Returns:
            None: Side-effect only.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CursorPollScheduler.stop)
            True
        """
        task = self._task
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        self._task = None
        logger.info("cursor_poll_scheduler: stopped")

    async def poll_once(self) -> int:
        """Run one sweep over all implementing cursor_cloud issues.

        Returns:
            int: Number of issues polled.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CursorPollScheduler.poll_once)
            True
        """
        polled = 0
        issues = list_issues(self._layout, limit=200)
        for issue in issues:
            if issue.state != "implementing":
                continue
            if issue.executor != "cursor_cloud":
                continue
            if not (issue.cursor_job_id or issue.cursor_agent_id):
                continue
            try:
                updated = await asyncio.to_thread(
                    poll_cursor_cloud_for_issue,
                    self._conn,
                    self._layout,
                    issue,
                    ws=self._ws,
                )
                polled += 1
                if self._fanout is not None:
                    payload: dict[str, object] = {
                        "issue_id": updated.id,
                        "event": "transition",
                        "state": updated.state,
                        "pipeline_stage": updated.pipeline_stage,
                    }
                    await self._fanout.publish(payload)  # type: ignore[arg-type]
                logger.debug(
                    "cursor_poll_scheduler: polled issue={} state={} stage={}",
                    updated.id,
                    updated.state,
                    updated.pipeline_stage,
                )
            except ExecutorBlockedError as exc:
                logger.warning(
                    "cursor_poll_scheduler: poll failed for issue={}: {}",
                    issue.id,
                    exc,
                )
            except Exception:
                logger.exception(
                    "cursor_poll_scheduler: unexpected error polling issue={}",
                    issue.id,
                )
        return polled

    async def _loop(self) -> None:
        """Run poll sweeps every ``_poll_interval_s`` seconds until cancelled.

        Returns:
            None: Runs until the background task is cancelled.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CursorPollScheduler._loop)
            True
        """
        while True:
            try:
                count = await self.poll_once()
                if count:
                    logger.debug("cursor_poll_scheduler: swept {} issue(s)", count)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("cursor_poll_scheduler_loop_failed")
            try:
                await asyncio.sleep(self._poll_interval_s)
            except asyncio.CancelledError:
                break


__all__ = ["CursorPollScheduler"]
