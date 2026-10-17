"""Per-agent turn pump and the host-wide running cap (D7)."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from sqlalchemy import select

from sevn.config import Settings
from sevn.domain.errors import DomainError
from sevn.domain.session import open_session
from sevn.log import logger
from sevn.protocol.hub import Hub
from sevn.runtime.base import Runtime, ToolDecision
from sevn.runtime.runtimes.pydantic_ai import PydanticAIRuntime
from sevn.runtime.turn import TurnRunner
from sevn.store.models import Job as JobRow
from sevn.store.models import Turn as TurnRow


class _Board:
    """Partial text and cancel flags for turns this worker has opened."""

    def __init__(self) -> None:
        self._text: dict[str, str] = {}
        self._agent: dict[str, str] = {}
        self._cancelled: set[str] = set()

    def open_turn(self, turn_id: str, agent_id: str) -> None:
        self._agent[turn_id] = agent_id
        self._text[turn_id] = ""

    def append(self, turn_id: str, text: str) -> None:
        self._text[turn_id] = self._text.get(turn_id, "") + text

    def text(self, turn_id: str) -> str:
        return self._text.get(turn_id, "")

    def cancel(self, turn_id: str) -> None:
        self._cancelled.add(turn_id)

    def cancelled(self, turn_id: str) -> bool:
        return turn_id in self._cancelled

    def agent_id(self, turn_id: str) -> str | None:
        return self._agent.get(turn_id)


class Worker:
    """Run queued jobs one turn at a time per agent, up to the host cap."""

    def __init__(self, hub: Hub, runtime: Runtime | None = None) -> None:
        self.hub = hub
        self._runtime = runtime if runtime is not None else PydanticAIRuntime()
        self._slots = asyncio.Semaphore(_max_running_turns())
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._again: set[str] = set()
        self._board = _Board()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def kick(self, agent_id: str) -> None:
        """Wake the agent's pump. Safe to call again while a turn is running."""
        if self._closed:
            return
        self._again.add(agent_id)
        task = self._tasks.get(agent_id)
        if task is None or task.done():
            started = asyncio.create_task(self._pump(agent_id))
            started.add_done_callback(_log_task)
            self._tasks[agent_id] = started

    async def aclose(self) -> None:
        """Stop pumps. Does not close the hub."""
        self._closed = True
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()

    async def resume(
        self,
        agent_id: str,
        turn_id: str,
        decisions: tuple[ToolDecision, ...],
    ) -> None:
        async with self._lock(agent_id):
            await self._slots.acquire()
            try:
                runner = TurnRunner(self.hub, self._runtime, watch=self._board)
                await runner.resume(turn_id, decisions)
            finally:
                self._slots.release()

    async def cancel(self, turn_id: str) -> None:
        self._board.cancel(turn_id)
        agent_id = self._board.agent_id(turn_id)
        if agent_id is None:
            agent_id = await _agent_for_turn(turn_id)
        await self._runtime.interrupt(agent_id)

    async def snapshot(self, turn_id: str) -> tuple[str, str]:
        status = await _turn_status(turn_id)
        return self._board.text(turn_id), status

    def _lock(self, agent_id: str) -> asyncio.Lock:
        lock = self._locks.get(agent_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[agent_id] = lock
        return lock

    async def _pump(self, agent_id: str) -> None:
        async with self._lock(agent_id):
            while not self._closed:
                self._again.discard(agent_id)
                job_id = await _next_queued(agent_id)
                if job_id is None:
                    if agent_id in self._again:
                        continue
                    return
                await self._slots.acquire()
                try:
                    await self._run(job_id)
                finally:
                    self._slots.release()

    async def _run(self, job_id: str) -> None:
        runner = TurnRunner(self.hub, self._runtime, watch=self._board)
        try:
            await runner.run(job_id)
        except Exception:  # noqa: BLE001 — one failed turn must not stop the agent pump
            logger.exception("turn failed")


_current: Worker | None = None


def bind(hub: Hub) -> Worker:
    """Return the worker for ``hub``, replacing one that has been closed."""
    global _current
    if _current is not None and not _current.closed and _current.hub is hub:
        return _current
    _current = Worker(hub)
    return _current


def current() -> Worker | None:
    if _current is None or _current.closed:
        return None
    return _current


def _max_running_turns() -> int:
    return Settings.load().runtime.max_running_turns


def _log_task(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.opt(exception=exc).error("worker pump failed")


async def _next_queued(agent_id: str) -> str | None:
    async with open_session() as session:
        return await session.scalar(
            select(JobRow.id)
            .where(JobRow.agent_id == agent_id)
            .where(JobRow.status == "queued")
            .order_by(JobRow.created_at, JobRow.id)
            .limit(1)
        )


async def _turn_status(turn_id: str) -> str:
    async with open_session() as session:
        row = await session.get(TurnRow, turn_id)
        if row is None:
            raise DomainError("not_found", "turn not found")
        return row.status


async def _agent_for_turn(turn_id: str) -> str:
    async with open_session() as session:
        row = await session.get(TurnRow, turn_id)
        if row is None:
            raise DomainError("not_found", "turn not found")
        return row.agent_id
