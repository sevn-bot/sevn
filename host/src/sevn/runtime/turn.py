"""TurnRunner: stream one job, coalesce ticks, and commit the turn (D4, D8)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.domain.agents import AgentRecord, AgentService
from sevn.domain.bots import BotRecord, BotService
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.log import logger
from sevn.protocol.hub import Hub
from sevn.runtime.base import Runtime, ToolDecision, TurnContext
from sevn.runtime.errors import TurnError
from sevn.runtime.events import ApprovalCall, RuntimeEvent
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import Event, Message
from sevn.store.models import Job as JobRow
from sevn.store.models import PendingRequest as PendingRow
from sevn.store.models import Turn as TurnRow


class TurnWatch(Protocol):
    """In-memory partial text and cancel flag for the turn the worker is running."""

    def open_turn(self, turn_id: str, agent_id: str) -> None: ...

    def append(self, turn_id: str, text: str) -> None: ...

    def cancelled(self, turn_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class _Job:
    id: str
    bot_id: str
    agent_id: str
    text: str


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


class TurnRunner:
    """Drive one runtime turn and persist it in a single end transaction."""

    def __init__(self, hub: Hub, runtime: Runtime, watch: TurnWatch | None = None) -> None:
        self._hub = hub
        self._runtime = runtime
        self._watch = watch

    async def run(self, job_id: str) -> None:
        job = await _mark_started(job_id)
        await self._hub.emit(
            "job.started",
            job.id,
            {"job_id": job.id, "agent_id": job.agent_id, "status": "started"},
        )
        agent = await AgentService().get(job.agent_id)
        bot = await BotService().get(job.bot_id)
        history = await _previous_messages(agent.id)
        turn_id = new_id("turn_")
        started = utcnow()
        stored = False
        if self._watch is not None:
            await _insert_open_turn(turn_id, started, job, agent, bot)
            self._watch.open_turn(turn_id, agent.id)
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
        await self._runtime.open(agent)
        try:
            outcome = await self._drive(turn_id, agent, bot, job, history, decisions)
            if self._watch is not None and self._watch.cancelled(turn_id):
                await self._persist_cancelled(turn_id, started, job, agent, bot, stored=stored)
            elif outcome.approvals:
                await self._persist_waiting(
                    turn_id, started, job, agent, bot, outcome, stored=stored
                )
            else:
                await self._persist_done(turn_id, started, job, agent, bot, outcome, stored=stored)
        finally:
            await self._runtime.close(agent.id)

    async def _drive(
        self,
        turn_id: str,
        agent: AgentRecord,
        bot: BotRecord,
        job: _Job,
        history: list[object] | None,
        decisions: tuple[ToolDecision, ...] | None,
    ) -> _Outcome:
        context = TurnContext(
            agent=agent,
            bot=bot,
            job_id=job.id,
            text=job.text,
            message_history=history,
            approvals=decisions,
        )
        parts: list[str] = []
        finished: RuntimeEvent | None = None
        async for event in self._runtime.run_turn(context):
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
        if finished is None or finished.model_messages is None:
            raise TurnError("turn produced no result")
        text = "".join(parts)
        if text == "" and finished.text:
            text = finished.text
        usage = finished.usage if finished.usage is not None else {}
        approvals = finished.approvals if finished.approvals is not None else ()
        return _Outcome(
            text=text,
            usage=usage,
            model_messages=finished.model_messages,
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
    ) -> None:
        finished_at = utcnow()
        async with open_session() as session:
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
            if not await _has_user_message(session, turn_id):
                user = _user_message(turn_id, started, job, agent)
                session.add(user)
                events.append(_message_event(user))
            assistant = _assistant_message(turn_id, finished_at, agent, bot, outcome.text)
            session.add(assistant)
            events.append(_message_event(assistant))
            await _finish_job(session, job.id, "done", finished_at)
            await _set_agent(session, agent.id, "idle", finished_at)
            events.append(_turn_event("turn.finished", turn_id, agent.id, "done"))
            events.append(_job_event("job.done", job.id, agent.id, "done"))
            events.append(_agent_event(agent.id, "idle"))
            for event in events:
                session.add(event)
            await session.commit()
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
            if not await _has_user_message(session, turn_id):
                user = _user_message(turn_id, started, job, agent)
                session.add(user)
                events.append(_message_event(user))
            for call in outcome.approvals:
                pending = _pending(turn_id, agent.id, call)
                session.add(pending)
                events.append(_pending_event(pending))
            await _set_agent(session, agent.id, "waiting", utcnow())
            events.append(_turn_event("turn.waiting", turn_id, agent.id, "waiting"))
            events.append(_agent_event(agent.id, "waiting"))
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
    ) -> None:
        finished_at = utcnow()
        async with open_session() as session:
            await _bind_turn(
                session,
                stored=stored,
                turn_id=turn_id,
                agent=agent,
                job=job,
                bot=bot,
                started=started,
                status="cancelled",
                usage={},
                model_messages=None,
                finished_at=finished_at,
            )
            await _finish_job(session, job.id, "cancelled", finished_at)
            await _set_agent(session, agent.id, "idle", finished_at)
            events = (
                _turn_event("turn.finished", turn_id, agent.id, "cancelled"),
                _agent_event(agent.id, "idle"),
            )
            for event in events:
                session.add(event)
            await session.commit()
            for event in events:
                await self._hub.relay(event)


def _text_parts(text: str) -> list[object]:
    part: dict[str, object] = {"type": "text", "text": text}
    return [part]


def _user_message(turn_id: str, started: datetime, job: _Job, agent: AgentRecord) -> Message:
    return Message(
        id=new_id("msg_"),
        thread_id=agent.thread_id,
        turn_id=turn_id,
        agent_id=agent.id,
        role="user",
        author="user",
        parts=_text_parts(job.text),
        created_at=started,
    )


def _assistant_message(
    turn_id: str,
    finished_at: datetime,
    agent: AgentRecord,
    bot: BotRecord,
    text: str,
) -> Message:
    return Message(
        id=new_id("msg_"),
        thread_id=agent.thread_id,
        turn_id=turn_id,
        agent_id=agent.id,
        role="assistant",
        author=bot.id,
        parts=_text_parts(text),
        created_at=finished_at,
    )


def _message_event(message: Message) -> Event:
    payload: dict[str, object] = {
        "message_id": message.id,
        "thread_id": message.thread_id,
        "turn_id": message.turn_id,
        "agent_id": message.agent_id,
        "role": message.role,
        "parts": message.parts,
    }
    return Event(
        type="message.created",
        entity=message.id,
        payload=payload,
        created_at=utcnow(),
    )


def _turn_event(event_type: str, turn_id: str, agent_id: str, status: str) -> Event:
    payload: dict[str, object] = {
        "turn_id": turn_id,
        "agent_id": agent_id,
        "status": status,
    }
    return Event(type=event_type, entity=turn_id, payload=payload, created_at=utcnow())


def _job_event(event_type: str, job_id: str, agent_id: str, status: str) -> Event:
    payload: dict[str, object] = {"job_id": job_id, "agent_id": agent_id, "status": status}
    return Event(type=event_type, entity=job_id, payload=payload, created_at=utcnow())


def _agent_event(agent_id: str, status: str) -> Event:
    payload: dict[str, object] = {"agent_id": agent_id, "status": status}
    return Event(type="agent.updated", entity=agent_id, payload=payload, created_at=utcnow())


def _pending(turn_id: str, agent_id: str, call: ApprovalCall) -> PendingRow:
    payload: dict[str, object] = {"name": call.name, "args": call.args}
    return PendingRow(
        id=new_id("pend_"),
        turn_id=turn_id,
        agent_id=agent_id,
        kind="approval",
        tool_call_id=call.tool_call_id,
        payload=payload,
        answer=None,
        status="waiting",
        created_at=utcnow(),
        resolved_at=None,
    )


def _pending_event(row: PendingRow) -> Event:
    payload: dict[str, object] = {
        "pending_id": row.id,
        "turn_id": row.turn_id,
        "agent_id": row.agent_id,
        "kind": row.kind,
    }
    return Event(type="pending.created", entity=row.id, payload=payload, created_at=utcnow())


async def _mark_started(job_id: str) -> _Job:
    async with open_session() as session:
        row = await session.get(JobRow, job_id)
        if row is None:
            raise TurnError("job not found")
        agent_id = row.agent_id
        if agent_id is None:
            raise TurnError("job has no agent")
        row.status = "started"
        if row.started_at is None:
            row.started_at = utcnow()
        await session.commit()
        return _Job(id=row.id, bot_id=row.to_bot_id, agent_id=agent_id, text=row.text)


async def _previous_messages(agent_id: str) -> list[object] | None:
    async with open_session() as session:
        row = await session.scalar(
            select(TurnRow)
            .where(TurnRow.agent_id == agent_id)
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
        await _set_agent(session, agent.id, "running", started)
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
        )
        agent_id = turn.agent_id
        bot_id = job_row.to_bot_id
        started = turn.started_at
    return _Loaded(
        job=job,
        agent=await AgentService().get(agent_id),
        bot=await BotService().get(bot_id),
        history=history,
        started=started,
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
        row.usage = usage
        row.model_messages = model_messages
        row.finished_at = finished_at
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
    return row


async def _has_user_message(session: AsyncSession, turn_id: str) -> bool:
    found = await session.scalar(
        select(Message.id).where(Message.turn_id == turn_id, Message.role == "user").limit(1)
    )
    return found is not None


async def _finish_job(session: AsyncSession, job_id: str, status: str, when: datetime) -> None:
    row = await session.get(JobRow, job_id)
    if row is None:
        raise TurnError("job not found")
    row.status = status
    row.finished_at = when


async def _set_agent(session: AsyncSession, agent_id: str, status: str, when: datetime) -> None:
    row = await session.get(AgentRow, agent_id)
    if row is None:
        return
    row.status = status
    row.last_activity_at = when
