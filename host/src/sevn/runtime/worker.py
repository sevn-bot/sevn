"""Per-agent turn pump and the host-wide running cap (D7)."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from sqlalchemy import select

from sevn.config import Settings
from sevn.domain.agents import AgentService, occupying, queued_agent_ids
from sevn.domain.errors import DomainError
from sevn.domain.jobs import park_job
from sevn.domain.session import open_session
from sevn.log import logger
from sevn.protocol.hub import Hub
from sevn.runtime.base import Runtime, ToolDecision
from sevn.runtime.runtimes.claude import ClaudeRuntime, installed_client
from sevn.runtime.runtimes.pydantic_ai import PydanticAIRuntime
from sevn.runtime.turn import TurnRunner
from sevn.runtime.turn_end import (
    cancel_persisted_waiting,
    persist_queued_cancel,
    persist_running_cancel,
    record_turn_failure,
)
from sevn.store.models import Agent as AgentRow
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

    def forget(self, turn_id: str) -> None:
        self._text.pop(turn_id, None)
        self._agent.pop(turn_id, None)
        self._cancelled.discard(turn_id)


class Worker:
    """Run queued jobs one turn at a time per agent, up to the host cap."""

    def __init__(self, hub: Hub, runtime: Runtime | None = None) -> None:
        self.hub = hub
        self._override = runtime
        self._pydantic = PydanticAIRuntime()
        self._claude = ClaudeRuntime(client=installed_client(), hub=hub)
        self._slots = asyncio.Semaphore(_max_running_turns())
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._resumes: set[asyncio.Task[None]] = set()
        self._again: set[str] = set()
        self._interrupted: set[asyncio.Task[None]] = set()
        self._admission = asyncio.Lock()
        self._reserved: set[str] = set()
        self._board = _Board()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    async def steer(self, agent_id: str, text: str) -> bool:
        """Inject ``text`` into a running pydantic turn. Claude queues instead."""
        if self._override is not None:
            return False
        agent = await AgentService().get(agent_id)
        if agent.runtime != "pydantic_ai":
            logger.info("steer queued; this runtime has no live enqueue")
            return False
        return self._pydantic.enqueue(agent_id, text)

    async def interrupt_and_requeue(self, job_id: str, agent_id: str) -> None:
        """Cancel the open turn for ``job_id`` and leave that job queued on ``agent_id``.

        A waiting turn is cancelled too, so its pending requests are resolved
        and the old agent is not left waiting on a job it no longer owns.
        """
        turn_id = await _open_turn_for_job(job_id)
        if turn_id is not None:
            await self.cancel(turn_id)
        await park_job(job_id, agent_id)

    def kick(self, agent_id: str) -> None:
        """Wake the agent's pump. Safe to call again while a turn is running."""
        if self._closed:
            return
        self._again.add(agent_id)
        task = self._tasks.get(agent_id)
        if task is None or task.done():
            started = asyncio.create_task(self._pump(agent_id))
            started.add_done_callback(_log_task)
            started.add_done_callback(lambda done: self._after_pump(agent_id, done))
            self._tasks[agent_id] = started

    async def settle(self, agent_id: str) -> None:
        """Let a kicked pump run until it finishes or blocks on the model."""
        task = self._tasks.get(agent_id)
        if task is None:
            return
        for _ in range(_SETTLE_TURNS):
            if task.done():
                return
            await _cede()

    def start_resume(
        self,
        agent_id: str,
        turn_id: str,
        decisions: tuple[ToolDecision, ...],
    ) -> None:
        """Continue an approved turn without holding the request that answered it."""
        task = asyncio.create_task(self.resume(agent_id, turn_id, decisions))
        self._resumes.add(task)
        task.add_done_callback(self._resumes.discard)

    async def aclose(self) -> None:
        """Stop pumps. Does not close the hub."""
        self._closed = True
        tasks = [task for task in (*self._tasks.values(), *self._resumes) if not task.done()]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        self._resumes.clear()
        self._interrupted.clear()

    async def resume(
        self,
        agent_id: str,
        turn_id: str,
        decisions: tuple[ToolDecision, ...],
    ) -> None:
        runtime = await self._choose(agent_id)
        try:
            async with self._lock(agent_id):
                await self._slots.acquire()
                try:
                    runner = TurnRunner(self.hub, runtime, watch=self._board)
                    try:
                        await runner.resume(turn_id, decisions)
                    except Exception as exc:  # noqa: BLE001 — record the failure, then continue
                        logger.exception("turn failed")
                        await record_turn_failure(self.hub, exc, turn_id=turn_id)
                finally:
                    self._slots.release()
        finally:
            await self._release(agent_id)

    async def cancel(self, turn_id: str) -> str:
        """Cancel a queued, live or waiting turn. A finished turn keeps its stored status."""
        live = self._board.agent_id(turn_id)
        self._board.cancel(turn_id)
        if await cancel_persisted_waiting(self.hub, turn_id):
            agent_id = live if live is not None else await _agent_for_turn(turn_id)
            await self._release(agent_id)
            return "cancelled"
        if await persist_queued_cancel(self.hub, turn_id):
            return "cancelled"
        if live is None:
            if await persist_running_cancel(self.hub, turn_id):
                return "cancelled"
            return await _turn_status(turn_id)
        await persist_running_cancel(self.hub, turn_id)
        runtime = await self._choose(live)
        await runtime.interrupt(live)
        pump = self._tasks.get(live)
        if pump is not None and pump.cancelling():
            # The interrupt cancelled this pump itself (the turn ran in it).
            self._interrupted.add(pump)
        self.kick(live)
        return "cancelled"

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
                if await _agent_is_waiting(agent_id):
                    if agent_id in self._again:
                        continue
                    return
                job_id = await _next_queued(agent_id)
                if job_id is None:
                    if agent_id in self._again:
                        continue
                    return
                if not await self._reserve(agent_id):
                    if agent_id in self._again:
                        continue
                    return
                try:
                    async with self._slots:
                        stuck = await self._run(job_id)
                finally:
                    self._reserved.discard(agent_id)
                if stuck:
                    logger.error("job stayed queued after its turn")
                    return
                await self._open_slots(agent_id)

    async def _reserve(self, agent_id: str) -> bool:
        """Serialize admission until the runner persists the running status."""
        async with self._admission:
            agent = await AgentService().get(agent_id)
            async with open_session() as session:
                active = set(
                    await session.scalars(
                        select(AgentRow.id).where(
                            AgentRow.bot_id == agent.bot_id,
                            AgentRow.status.in_(("running", "waiting")),
                        )
                    )
                )
                reserved = set(
                    await session.scalars(
                        select(AgentRow.id).where(
                            AgentRow.bot_id == agent.bot_id, AgentRow.id.in_(self._reserved)
                        )
                    )
                )
            if len((active | reserved) - {agent_id}) >= Settings.load().bots.max_parallel_agents:
                return False
            self._reserved.add(agent_id)
            return True

    def _after_pump(self, agent_id: str, task: asyncio.Task[None]) -> None:
        """An interrupted turn cancels its pump before the pump's own wake-ups run.

        Release the agent from here instead, or jobs queued on it and lanes queued
        behind the bot's cap stay queued until the next message or a restart.
        """
        interrupted = task in self._interrupted
        self._interrupted.discard(task)
        # Only the pump cancel() interrupted counts: loop shutdown cancels pumps
        # too, and a task started while the loop closes is never run or reaped.
        if not task.cancelled() or not interrupted or self._closed:
            return
        released = asyncio.create_task(self._release(agent_id))
        self._resumes.add(released)
        released.add_done_callback(self._resumes.discard)

    async def _release(self, agent_id: str) -> None:
        """A turn outside the pump ended: wake this lane, then the lanes queued on its slot.

        The pump frees a slot itself after an ordinary job. A resumed approval, a
        cancelled waiting turn or an interrupted pump frees one without passing
        through it.
        """
        self.kick(agent_id)
        if self._closed:
            return
        try:
            await self._open_slots(agent_id)
        except Exception:  # noqa: BLE001 — a failed wake-up must not fail the resume or cancel
            logger.exception("could not wake queued lanes")

    async def _run(self, job_id: str) -> bool:
        """Run one job. True means it is still queued and must not be retried in a loop."""
        runtime = await self._choose(await _agent_id_for_job(job_id))
        runner = TurnRunner(self.hub, runtime, watch=self._board)
        try:
            await runner.run(job_id)
        except Exception as exc:  # noqa: BLE001 — one failed turn must not stop the agent pump
            logger.exception("turn failed")
            await record_turn_failure(self.hub, exc, job_id=job_id)
            return await _job_queued(job_id)
        return False

    async def _open_slots(self, agent_id: str) -> None:
        """Start queued agents when a finished turn frees a per-bot slot."""
        agent = await AgentService().get(agent_id)
        limit = Settings.load().bots.max_parallel_agents
        active = await occupying(agent.bot_id)
        slots = limit - active
        if slots <= 0:
            return
        for other in await queued_agent_ids(agent.bot_id):
            if other == agent_id or slots <= 0:
                continue
            self.kick(other)
            slots -= 1

    async def _choose(self, agent_id: str | None) -> Runtime:
        if self._override is not None:
            return self._override
        if agent_id is None:
            return self._pydantic
        agent = await AgentService().get(agent_id)
        if agent.runtime == "claude":
            return self._claude
        return self._pydantic


_SETTLE_TURNS = 2000
_current: Worker | None = None


async def _cede() -> None:
    """Yield once without ``asyncio.sleep``, which hangs under a frozen clock."""
    loop = asyncio.get_running_loop()
    ready: asyncio.Future[None] = loop.create_future()
    loop.call_soon(ready.set_result, None)
    await ready


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


async def _agent_is_waiting(agent_id: str) -> bool:
    """True while this agent has a turn paused for approval."""
    async with open_session() as session:
        found = await session.scalar(
            select(TurnRow.id)
            .where(TurnRow.agent_id == agent_id)
            .where(TurnRow.status == "waiting")
            .limit(1)
        )
    return found is not None


async def _job_queued(job_id: str) -> bool:
    async with open_session() as session:
        status = await session.scalar(select(JobRow.status).where(JobRow.id == job_id))
    return status == "queued"


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


async def _agent_id_for_job(job_id: str) -> str | None:
    async with open_session() as session:
        row = await session.get(JobRow, job_id)
        if row is None:
            return None
        return row.agent_id


async def _open_turn_for_job(job_id: str) -> str | None:
    async with open_session() as session:
        rows = list(
            await session.scalars(select(TurnRow).where(TurnRow.status.in_(("running", "waiting"))))
        )
        for row in rows:
            if job_id in row.job_ids:
                return row.id
    return None


async def _agent_for_turn(turn_id: str) -> str:
    async with open_session() as session:
        row = await session.get(TurnRow, turn_id)
        if row is None:
            raise DomainError("not_found", "turn not found")
        return row.agent_id
