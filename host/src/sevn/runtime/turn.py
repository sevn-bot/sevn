"""TurnRunner: stream one job, coalesce ticks, and commit the turn (D4, D8)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.decisions.base import DEFAULT_PROFILE, ContextProfile
from sevn.decisions.registry import begin_inbound, end_inbound, inbound_hits
from sevn.domain.agents import AgentRecord, AgentService
from sevn.domain.bots import BotRecord, BotService
from sevn.domain.ids import new_id
from sevn.domain.jobs import job_lock
from sevn.domain.pending import PendingService
from sevn.domain.session import open_session
from sevn.domain.workspace import drop_locks
from sevn.log import logger
from sevn.memory.context import capture_after_turn
from sevn.memory.store import MemoryStore
from sevn.observability.spans import ToolSpans, cli_tool_spans, turn_result, turn_span
from sevn.protocol.hub import Hub
from sevn.runtime.approvals import (
    auto_low,
    pending_row,
    question_message,
)
from sevn.runtime.base import Runtime, ToolDecision, TurnContext
from sevn.runtime.context_selection import select_history, turn_profile
from sevn.runtime.errors import TurnError
from sevn.runtime.events import ApprovalCall, RuntimeEvent
from sevn.runtime.turn_end import (
    failure_text,
)
from sevn.runtime.turn_store import (
    agent_event,
    assistant_message,
    finish_job,
    has_user_message,
    job_event,
    message_event,
    pending_event,
    resolve_open_pendings,
    set_agent,
    text_parts,
    turn_event,
)
from sevn.runtime.usage import combine as combine_usage
from sevn.runtime.usage import interrupted_usage
from sevn.store.db import utcnow
from sevn.store.models import DecisionLog, Event, Message
from sevn.store.models import Job as JobRow
from sevn.store.models import Turn as TurnRow
from sevn.tools.routine import is_silent_reply, mark_jobs_silent


class TurnWatch(Protocol):
    """In-memory partial text and cancel flag for the turn the worker is running."""

    def open_turn(self, turn_id: str, agent_id: str) -> None: ...

    def append(self, turn_id: str, text: str) -> None: ...

    def cancelled(self, turn_id: str) -> bool: ...

    def forget(self, turn_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class _Job:
    id: str
    bot_id: str
    agent_id: str
    text: str
    origin: str = "user"
    trace_parent: str | None = None
    profile: ContextProfile = DEFAULT_PROFILE


@dataclass(frozen=True, slots=True)
class _Outcome:
    text: str
    usage: dict[str, object]
    model_messages: list[object]
    approvals: tuple[ApprovalCall, ...]


@dataclass(frozen=True, slots=True)
class _Loaded:
    job: _Job
    agent: AgentRecord
    bot: BotRecord
    history: list[object]
    started: datetime
    status: str


class TurnRunner:
    """Drive one runtime turn and persist it in a single end transaction."""

    def __init__(self, hub: Hub, runtime: Runtime, watch: TurnWatch | None = None) -> None:
        self._hub = hub
        self._runtime = runtime
        self._watch = watch

    async def run(self, job_id: str, *, agent_id: str | None = None) -> None:
        async with job_lock(job_id):
            job = await _mark_started(job_id, agent_id=agent_id)
            if job is None:
                logger.info("job cancelled before it started")
                return
            await self._hub.emit(
                "job.started",
                job.id,
                {"job_id": job.id, "agent_id": job.agent_id, "status": "started"},
            )
            agent = await AgentService().get(job.agent_id)
            bot = await BotService().get(job.bot_id)
            history = await _previous_messages(agent.id)
            started = utcnow()
            stored = False
            existing = await _queued_turn_id(job.id)
            # Register the turn before its row is visible, so a cancel that reads the
            # row also finds the live turn and interrupts it.
            if existing is not None:
                turn_id = existing
                if self._watch is not None:
                    self._watch.open_turn(turn_id, agent.id)
                    await _promote_turn(turn_id, started, agent, bot)
                    stored = True
            else:
                turn_id = new_id("turn_")
                if self._watch is not None:
                    self._watch.open_turn(turn_id, agent.id)
                    await _insert_open_turn(turn_id, started, job, agent, bot)
                    stored = True
        await self._hub.emit(
            "turn.started",
            turn_id,
            {"turn_id": turn_id, "agent_id": agent.id, "status": "running"},
        )
        with logger.contextualize(bot_id=bot.id, agent_id=agent.id, turn_id=turn_id):
            logger.info("turn started")
            await self._finish(turn_id, started, job, agent, bot, history, None, stored=stored)
            logger.info("turn finished")

    async def resume(self, turn_id: str, decisions: tuple[ToolDecision, ...]) -> None:
        loaded = await _load_resume(turn_id)
        async with job_lock(loaded.job.id):
            loaded = await _load_resume(turn_id)
            if loaded.status not in {"waiting", "running"}:
                return
            await _mark_running(turn_id)
            if self._watch is not None:
                self._watch.open_turn(turn_id, loaded.agent.id)
        with logger.contextualize(
            bot_id=loaded.bot.id,
            agent_id=loaded.agent.id,
            turn_id=turn_id,
        ):
            logger.info("turn resumed")
            await self._finish(
                turn_id,
                loaded.started,
                loaded.job,
                loaded.agent,
                loaded.bot,
                loaded.history,
                decisions,
                stored=True,
            )
            logger.info("turn finished")

    async def _finish(
        self,
        turn_id: str,
        started: datetime,
        job: _Job,
        agent: AgentRecord,
        bot: BotRecord,
        history: list[object] | None,
        decisions: tuple[ToolDecision, ...] | None,
        *,
        stored: bool,
    ) -> None:
        # The turn joins the message's trace through the job row, never through the
        # context this task inherited, so a restart or another task keeps it (D5).
        with turn_span(
            job.trace_parent,
            turn_id=turn_id,
            job_id=job.id,
            agent_id=agent.id,
            bot_id=bot.id,
            runtime=agent.runtime,
            model=bot.model,
        ):
            await self._finish_turn(
                turn_id, started, job, agent, bot, history, decisions, stored=stored
            )

    async def _finish_turn(
        self,
        turn_id: str,
        started: datetime,
        job: _Job,
        agent: AgentRecord,
        bot: BotRecord,
        history: list[object] | None,
        decisions: tuple[ToolDecision, ...] | None,
        *,
        stored: bool,
    ) -> None:
        token = begin_inbound()
        profile_token = turn_profile.set(job.profile)
        try:
            await self._runtime.open(agent)
            try:
                # Usage of the drives that finished, kept if a later one stops.
                spent: dict[str, object] = {}
                try:
                    outcome = await self._drive(turn_id, agent, bot, job, history, decisions)
                    # Under ``auto`` a low-risk shell command does not need the user.
                    # Approve the whole batch only when every call is low risk; a
                    # mixed batch still asks so the risky call is visible.
                    while outcome.approvals and all(
                        auto_low(bot, call) for call in outcome.approvals
                    ):
                        auto = tuple(
                            ToolDecision(tool_call_id=call.tool_call_id, approved=True)
                            for call in outcome.approvals
                        )
                        # The approvals answer the calls on the latest response,
                        # so the next drive needs the history that ends with it.
                        spent = outcome.usage
                        try:
                            outcome = await self._drive(
                                turn_id, agent, bot, job, outcome.model_messages, auto
                            )
                        except TurnError as exc:
                            exc.usage = combine_usage(
                                spent, exc.usage if exc.usage is not None else interrupted_usage()
                            )
                            raise
                        # Each auto-approved drive is another model run of
                        # this turn; keep what the earlier runs used.
                        outcome = replace(outcome, usage=combine_usage(spent, outcome.usage))
                except asyncio.CancelledError:
                    if self._watch is not None and self._watch.cancelled(turn_id):
                        await MemoryStore().rollback(turn_id)
                        await self._persist_cancelled(
                            turn_id,
                            started,
                            job,
                            agent,
                            bot,
                            stored=stored,
                            usage=combine_usage(spent, interrupted_usage()),
                        )
                    raise
                noted = inbound_hits()
                if self._watch is not None and self._watch.cancelled(turn_id):
                    await MemoryStore().rollback(turn_id)
                    await self._persist_cancelled(
                        turn_id, started, job, agent, bot, stored=stored, usage=outcome.usage
                    )
                elif outcome.approvals or await PendingService().has_waiting(turn_id):
                    # A question marks the turn waiting before this final write.
                    # If cancelled now, finish the transaction before the worker
                    # persists cancellation; interrupting a SQLite statement can
                    # leave its writer lock held until the cursor is collected.
                    saving = asyncio.create_task(
                        self._persist_waiting(
                            turn_id, started, job, agent, bot, outcome, stored=stored
                        )
                    )
                    cancelled = False
                    try:
                        while not saving.done():
                            try:
                                await asyncio.shield(saving)
                            except asyncio.CancelledError:
                                cancelled = True
                        saving.result()
                    except Exception:
                        if not cancelled:
                            raise
                        logger.exception("waiting turn persistence failed during cancellation")
                    if cancelled:
                        raise asyncio.CancelledError
                else:
                    await self._persist_done(
                        turn_id,
                        started,
                        job,
                        agent,
                        bot,
                        outcome,
                        stored=stored,
                        noted=noted,
                    )
            except Exception:
                await MemoryStore().rollback(turn_id)
                raise
            finally:
                await self._runtime.close(agent.id)
                if self._watch is not None:
                    self._watch.forget(turn_id)
        finally:
            turn_profile.reset(profile_token)
            end_inbound(token)

    async def _drive(
        self,
        turn_id: str,
        agent: AgentRecord,
        bot: BotRecord,
        job: _Job,
        history: list[object] | None,
        decisions: tuple[ToolDecision, ...] | None,
    ) -> _Outcome:
        selected = select_history(history, job.profile, resuming=decisions is not None)
        context = TurnContext(
            agent=agent,
            bot=bot,
            job_id=job.id,
            text=job.text,
            turn_id=turn_id,
            message_history=selected,
            approvals=decisions,
            ephemeral=job.origin == "chit_chat",
        )
        parts: list[str] = []
        finished: RuntimeEvent | None = None
        error_code: str | None = None
        error_usage: dict[str, object] | None = None
        async for event in _traced_tools(agent.runtime, self._runtime.run_turn(context)):
            if event.kind == "text_delta" and event.text:
                parts.append(event.text)
                if self._watch is not None:
                    self._watch.append(turn_id, event.text)
                self._hub.tick(
                    "turn.delta",
                    turn_id,
                    {"turn_id": turn_id, "agent_id": agent.id, "text": event.text},
                )
            elif event.kind == "turn_finished":
                finished = event
            elif event.kind == "error" and error_code is None:
                error_code = event.code if event.code else "error"
                error_usage = event.usage
        if finished is None or finished.model_messages is None:
            if self._watch is not None and self._watch.cancelled(turn_id):
                stopped = error_usage if error_usage is not None else interrupted_usage()
                return _Outcome(text="", usage=stopped, model_messages=[], approvals=())
            if error_code is not None:
                # ``message`` can echo the prompt. Keep the code, store fixed text.
                logger.warning("runtime error {code}", code=error_code)
                raise TurnError(failure_text("".join(parts)), usage=error_usage)
            raise TurnError("turn produced no result")
        text = "".join(parts)
        if text == "" and finished.text:
            text = finished.text
        usage = finished.usage if finished.usage is not None else {}
        approvals = finished.approvals if finished.approvals is not None else ()
        messages = finished.model_messages
        if (
            history is not None
            and selected is not history
            and finished.new_message_count is not None
        ):
            # Keep the full archive, including attachments, for later full turns and resumes.
            new = messages[-finished.new_message_count :] if finished.new_message_count else []
            messages = [*history, *new]
        return _Outcome(
            text=text,
            usage=usage,
            model_messages=messages,
            approvals=approvals,
        )

    async def _persist_done(
        self,
        turn_id: str,
        started: datetime,
        job: _Job,
        agent: AgentRecord,
        bot: BotRecord,
        outcome: _Outcome,
        *,
        stored: bool,
        noted: list[str] | None = None,
    ) -> None:
        finished_at = utcnow()
        async with open_session() as session:
            if await _is_cancelled(session, turn_id):
                await MemoryStore().rollback(turn_id)
                return
            await MemoryStore().write(session, turn_id)
            await _bind_turn(
                session,
                stored=stored,
                turn_id=turn_id,
                agent=agent,
                job=job,
                bot=bot,
                started=started,
                status="done",
                usage=outcome.usage,
                model_messages=outcome.model_messages,
                finished_at=finished_at,
            )
            events: list[Event] = []
            if not await has_user_message(session, turn_id):
                user = _user_message(turn_id, started, job, agent)
                session.add(user)
                events.append(message_event(user))
            extra = [{"type": "injection", "text": item} for item in noted or []]
            assistant = assistant_message(
                turn_id,
                finished_at,
                agent,
                bot,
                outcome.text,
                extra=extra or None,
            )
            session.add(assistant)
            events.append(message_event(assistant))
            await finish_job(session, job.id, "done", finished_at)
            if is_silent_reply(outcome.text):
                # A Claude routine run has no routine.silent tool; its reply says it.
                await mark_jobs_silent(session, [job.id])
            agent_status = "done" if job.origin == "chit_chat" else "idle"
            await set_agent(session, agent.id, agent_status, finished_at)
            events.append(turn_event("turn.finished", turn_id, agent.id, "done"))
            events.append(job_event("job.done", job.id, agent.id, "done"))
            events.append(agent_event(agent.id, agent_status))
            for event in events:
                session.add(event)
            await drop_locks(session, agent.id)
            await session.commit()
            await capture_after_turn(agent.id, job.text)
            for event in events:
                await self._hub.relay(event)

    async def _persist_waiting(
        self,
        turn_id: str,
        started: datetime,
        job: _Job,
        agent: AgentRecord,
        bot: BotRecord,
        outcome: _Outcome,
        *,
        stored: bool,
    ) -> None:
        async with open_session() as session:
            if await _is_cancelled(session, turn_id):
                return
            await _bind_turn(
                session,
                stored=stored,
                turn_id=turn_id,
                agent=agent,
                job=job,
                bot=bot,
                started=started,
                status="waiting",
                usage=outcome.usage,
                model_messages=outcome.model_messages,
                finished_at=None,
            )
            events: list[Event] = []
            if not await has_user_message(session, turn_id):
                user = _user_message(turn_id, started, job, agent)
                session.add(user)
                events.append(message_event(user))
            for call in outcome.approvals:
                pending = pending_row(turn_id, agent.id, call)
                session.add(pending)
                events.append(pending_event(pending))
            asked = await question_message(session, turn_id, agent, bot, outcome.text)
            if asked is not None:
                session.add(asked)
                events.append(message_event(asked))
            await set_agent(session, agent.id, "waiting", utcnow())
            events.append(turn_event("turn.waiting", turn_id, agent.id, "waiting"))
            events.append(agent_event(agent.id, "waiting"))
            for event in events:
                session.add(event)
            await session.commit()
            for event in events:
                await self._hub.relay(event)

    async def _persist_cancelled(
        self,
        turn_id: str,
        started: datetime,
        job: _Job,
        agent: AgentRecord,
        bot: BotRecord,
        *,
        stored: bool,
        usage: dict[str, object],
    ) -> None:
        finished_at = utcnow()
        async with open_session() as session:
            if await _is_cancelled(session, turn_id):
                return
            turn = await _bind_turn(
                session,
                stored=stored,
                turn_id=turn_id,
                agent=agent,
                job=job,
                bot=bot,
                started=started,
                status="cancelled",
                usage=usage,
                model_messages=None,
                finished_at=finished_at,
            )
            events: list[Event] = []
            if not await has_user_message(session, turn_id):
                user = _user_message(turn_id, started, job, agent)
                session.add(user)
                events.append(message_event(user))
            await finish_job(session, job.id, "cancelled", finished_at)
            await set_agent(session, agent.id, "idle", finished_at)
            events.append(turn_event("turn.finished", turn_id, agent.id, "cancelled"))
            events.append(job_event("job.done", job.id, agent.id, "cancelled"))
            events.append(agent_event(agent.id, "idle"))
            events.extend(await resolve_open_pendings(session, turn, finished_at))
            for event in events:
                session.add(event)
            await drop_locks(session, agent.id)
            await session.commit()
            for event in events:
                await self._hub.relay(event)


def _traced_tools(runtime: str, events: AsyncIterator[RuntimeEvent]) -> AsyncIterator[RuntimeEvent]:
    """``events``, with ``tool.<name>`` spans opened from a CLI runtime's tool events.

    Pydantic AI turns and untraced turns get the runtime's stream itself.
    """
    tools = cli_tool_spans(runtime)
    if tools is None:
        return events
    return _with_tool_spans(tools, events)


async def _with_tool_spans(
    tools: ToolSpans, events: AsyncIterator[RuntimeEvent]
) -> AsyncIterator[RuntimeEvent]:
    try:
        async for event in events:
            if event.name and event.kind == "tool_call_started":
                tools.start(event.name, event.args)
            elif event.name and event.kind == "tool_call_finished":
                tools.finish(event.name, ok=event.ok)
            yield event
    finally:
        tools.close()


def _user_message(turn_id: str, started: datetime, job: _Job, agent: AgentRecord) -> Message:
    return Message(
        id=new_id("msg_"),
        thread_id=agent.thread_id,
        turn_id=turn_id,
        agent_id=agent.id,
        role="user",
        author="user",
        parts=text_parts(job.text),
        created_at=started,
    )


async def _mark_started(job_id: str, *, agent_id: str | None = None) -> _Job | None:
    """Atomically claim queued work, only for the lane that selected it."""
    async with open_session() as session:
        stmt = update(JobRow).where(JobRow.id == job_id, JobRow.status == "queued")
        if agent_id is not None:
            stmt = stmt.where(JobRow.agent_id == agent_id)
        row = await session.scalar(
            stmt.values(status="started", started_at=utcnow()).returning(JobRow)
        )
        if row is None:
            return None
        if row.agent_id is None:
            raise TurnError("job has no agent")
        await session.commit()
        return _Job(
            id=row.id,
            bot_id=row.to_bot_id,
            agent_id=row.agent_id,
            text=row.text,
            origin=row.origin,
            trace_parent=row.trace_parent,
            profile=await _job_profile(session, row),
        )


async def _job_profile(session: AsyncSession, job: JobRow) -> ContextProfile:
    if job.route_decision_id:
        row = await session.get(DecisionLog, job.route_decision_id)
        if row is not None:
            return ContextProfile.model_validate(row.answers.get("context_profile") or {})
    return DEFAULT_PROFILE


async def _previous_messages(agent_id: str) -> list[object] | None:
    """History for a new turn. A waiting turn still ends on an open tool call."""
    async with open_session() as session:
        row = await session.scalar(
            select(TurnRow)
            .where(TurnRow.agent_id == agent_id)
            .where(TurnRow.status == "done")
            .where(TurnRow.model_messages.is_not(None))
            .order_by(TurnRow.started_at.desc())
            .limit(1)
        )
        if row is None or row.model_messages is None:
            return None
        return list(row.model_messages)


async def _insert_open_turn(
    turn_id: str,
    started: datetime,
    job: _Job,
    agent: AgentRecord,
    bot: BotRecord,
) -> None:
    async with open_session() as session:
        session.add(
            TurnRow(
                id=turn_id,
                agent_id=agent.id,
                thread_id=agent.thread_id,
                job_ids=[job.id],
                status="running",
                model=bot.model,
                usage={},
                model_messages=None,
                started_at=started,
                finished_at=None,
            )
        )
        await set_agent(session, agent.id, "running", started)
        await session.commit()


async def _mark_running(turn_id: str) -> None:
    async with open_session() as session:
        row = await session.get(TurnRow, turn_id)
        if row is None or row.status != "waiting":
            return
        row.status = "running"
        await set_agent(session, row.agent_id, "running", utcnow())
        await session.commit()


async def _load_resume(turn_id: str) -> _Loaded:
    async with open_session() as session:
        turn = await session.get(TurnRow, turn_id)
        if turn is None or len(turn.job_ids) == 0:
            raise TurnError("turn not found")
        job_row = await session.get(JobRow, turn.job_ids[0])
        if job_row is None or job_row.agent_id is None:
            raise TurnError("job not found")
        history = list(turn.model_messages) if turn.model_messages is not None else []
        job = _Job(
            id=job_row.id,
            bot_id=job_row.to_bot_id,
            agent_id=job_row.agent_id,
            text=job_row.text,
            origin=job_row.origin,
            trace_parent=job_row.trace_parent,
            profile=await _job_profile(session, job_row),
        )
        agent_id = turn.agent_id
        bot_id = job_row.to_bot_id
        started = turn.started_at
        status = turn.status
    return _Loaded(
        job=job,
        agent=await AgentService().get(agent_id),
        bot=await BotService().get(bot_id),
        history=history,
        started=started,
        status=status,
    )


async def _bind_turn(
    session: AsyncSession,
    *,
    stored: bool,
    turn_id: str,
    agent: AgentRecord,
    job: _Job,
    bot: BotRecord,
    started: datetime,
    status: str,
    usage: dict[str, object],
    model_messages: list[object] | None,
    finished_at: datetime | None,
) -> TurnRow:
    if stored:
        row = await session.get(TurnRow, turn_id)
        if row is None:
            raise TurnError("turn not found")
        row.status = status
        row.model = bot.model
        # A resumed turn already stored the usage of its runs before the pause.
        row.usage = combine_usage(row.usage or {}, usage)
        row.model_messages = model_messages
        row.finished_at = finished_at
        turn_result(status=status, model=row.model, usage=row.usage)
        return row
    row = TurnRow(
        id=turn_id,
        agent_id=agent.id,
        thread_id=agent.thread_id,
        job_ids=[job.id],
        status=status,
        model=bot.model,
        usage=usage,
        model_messages=model_messages,
        started_at=started,
        finished_at=finished_at,
    )
    session.add(row)
    await session.flush()
    turn_result(status=status, model=row.model, usage=row.usage)
    return row


async def _is_cancelled(session: AsyncSession, turn_id: str) -> bool:
    status = await session.scalar(select(TurnRow.status).where(TurnRow.id == turn_id))
    return status == "cancelled"


async def _queued_turn_id(job_id: str) -> str | None:
    async with open_session() as session:
        rows = list(await session.scalars(select(TurnRow).where(TurnRow.status == "queued")))
        for row in rows:
            if job_id in row.job_ids:
                return row.id
    return None


async def _promote_turn(
    turn_id: str,
    started: datetime,
    agent: AgentRecord,
    bot: BotRecord,
) -> None:
    async with open_session() as session:
        row = await session.get(TurnRow, turn_id)
        if row is None:
            raise TurnError("turn not found")
        row.status = "running"
        row.agent_id = agent.id
        row.thread_id = agent.thread_id
        row.model = bot.model
        row.started_at = started
        messages = list(await session.scalars(select(Message).where(Message.turn_id == turn_id)))
        for message in messages:
            message.agent_id = agent.id
            message.thread_id = agent.thread_id
        await set_agent(session, agent.id, "running", started)
        await session.commit()
