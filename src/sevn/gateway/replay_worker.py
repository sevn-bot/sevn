"""Async dashboard turn-replay worker (`specs/16-harness-discipline.md` §4.4).

Module: sevn.gateway.replay_worker
Depends: asyncio, sqlite3, sevn.gateway.channel_router, sevn.gateway.replay_job_events,
    sevn.gateway.replay_turn_lookup, sevn.gateway.session_manager

Exports:
    ReplayJobRequest — queued replay work unit.
    TurnReplayWorker — in-memory queue draining into ``enqueue_dispatch``.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from sevn.gateway.replay_job_events import ReplayJobEventFanoutFn, ReplayJobEventPayload
from sevn.gateway.replay_turn_lookup import lookup_user_text_for_turn

if TYPE_CHECKING:
    import sqlite3

    from sevn.gateway.channel_router import ChannelRouter


@dataclass(frozen=True, slots=True)
class ReplayJobRequest:
    """One dashboard replay job waiting for dispatch."""

    replay_job_id: str
    session_id: str
    turn_id: str


class TurnReplayWorker:
    """Drain queued replay jobs into the live gateway turn pipeline."""

    def __init__(
        self,
        *,
        sqlite_conn: sqlite3.Connection,
        gateway_router: ChannelRouter,
        job_event_fanout: ReplayJobEventFanoutFn | None = None,
        poll_interval_s: float = 0.25,
    ) -> None:
        """Bind runtime dependencies for the async replay worker loop.

        Args:
            sqlite_conn (sqlite3.Connection): Shared gateway database handle.
            gateway_router (ChannelRouter): Router exposing ``_run_turn``.
            job_event_fanout (ReplayJobEventFanoutFn | None): Optional lifecycle publisher.
            poll_interval_s (float): Idle poll interval when the queue is empty.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(TurnReplayWorker.schedule)
            True
        """
        self._sqlite_conn = sqlite_conn
        self._router = gateway_router
        self._job_event_fanout = job_event_fanout
        self._poll_interval_s = poll_interval_s
        self._queue: deque[ReplayJobRequest] = deque()
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def schedule(
        self,
        replay_job_id: str,
        *,
        session_id: str,
        turn_id: str,
    ) -> None:
        """Enqueue one replay job and wake the background loop.

        Args:
            replay_job_id (str): Stable replay job identifier.
            session_id (str): Gateway session id.
            turn_id (str): Historical user turn id to replay.

        Returns:
            None: Side-effect only.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(TurnReplayWorker.schedule)
            True
        """
        self._queue.append(
            ReplayJobRequest(
                replay_job_id=replay_job_id,
                session_id=session_id,
                turn_id=turn_id,
            ),
        )
        self._wake.set()

    async def start(self) -> None:
        """Start the background polling loop.

        Returns:
            None: Side-effect only.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TurnReplayWorker.start)
            True
        """
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Cancel and join the background loop.

        Returns:
            None: Side-effect only.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TurnReplayWorker.stop)
            True
        """
        task = self._task
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        self._task = None

    async def process_once(self) -> bool:
        """Dispatch one queued replay job when present.

        Returns:
            bool: ``True`` when a job was drained from the queue.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TurnReplayWorker.process_once)
            True
        """
        if not self._queue:
            return False
        job = self._queue.popleft()
        await self._process_job(job)
        return True

    async def _loop(self) -> None:
        """Poll for queued replay jobs until cancelled.

        Returns:
            None: Runs until the background task is cancelled.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TurnReplayWorker._loop)
            True
        """
        while True:
            try:
                processed = await self.process_once()
                if processed:
                    continue
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=self._poll_interval_s)
                self._wake.clear()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("replay_worker_loop_failed")

    async def _process_job(self, job: ReplayJobRequest) -> None:
        """Stage replay text and enqueue one gateway turn dispatch.

        Args:
            job (ReplayJobRequest): Queued replay work unit.

        Returns:
            None: Side-effect only.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TurnReplayWorker._process_job)
            True
        """
        await self._publish(
            {
                "replay_job_id": job.replay_job_id,
                "session_id": job.session_id,
                "turn_id": job.turn_id,
                "event": "transition",
                "status": "running",
            },
        )
        user_text = await asyncio.to_thread(
            lookup_user_text_for_turn,
            self._sqlite_conn,
            job.session_id,
            job.turn_id,
        )
        if user_text is None:
            await self._publish(
                {
                    "replay_job_id": job.replay_job_id,
                    "session_id": job.session_id,
                    "turn_id": job.turn_id,
                    "event": "terminal",
                    "status": "failed",
                    "message": "no replayable user message for turn",
                },
            )
            return
        self._router._sessions.set_replay_target(
            job.session_id,
            user_text=user_text,
            origin_turn_id=job.turn_id,
            replay_job_id=job.replay_job_id,
        )
        correlation_id = uuid.uuid4().hex
        logger.info(
            "replay_worker_dispatch session_id={} origin_turn_id={} replay_job_id={} correlation_id={}",
            job.session_id,
            job.turn_id,
            job.replay_job_id,
            correlation_id,
        )
        await self._router._sessions.enqueue_dispatch(
            job.session_id,
            correlation_id=correlation_id,
            queue_mode=self._router._queue_mode,
            dispatch=self._router._run_turn,
        )
        await self._publish(
            {
                "replay_job_id": job.replay_job_id,
                "session_id": job.session_id,
                "turn_id": job.turn_id,
                "event": "transition",
                "status": "dispatched",
            },
        )

    async def _publish(self, payload: ReplayJobEventPayload) -> None:
        """Best-effort replay job lifecycle fan-out.

        Args:
            payload (ReplayJobEventPayload): Event body for dashboard subscribers.

        Returns:
            None: Side-effect only.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TurnReplayWorker._publish)
            True
        """
        if self._job_event_fanout is None:
            return
        try:
            await self._job_event_fanout(payload)
        except Exception:
            logger.exception(
                "replay_job_event_publish_failed replay_job_id={}",
                payload.get("replay_job_id"),
            )


__all__ = ["ReplayJobRequest", "TurnReplayWorker"]
