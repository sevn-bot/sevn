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
from sevn.memory.context import capture_after_turn
from sevn.memory.store import MemoryStore
from sevn.protocol.hub import Hub
from sevn.runtime.base import Runtime, ToolDecision, TurnContext
from sevn.runtime.errors import ModelError, TurnError
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
    origin: str = "user"


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
        started = utcnow()
        stored = False
        existing = await _queued_turn_id(job.id)
        if existing is not None:
            turn_id = existing
            if self._watch is not None:
                await _promote_turn(turn_id, started, agent, bot)
                self._watch.open_turn(turn_id, agent.id)
                stored = True
        else:
            turn_id = new_id("turn_")
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
        if self._watch is not None and self._watch.cancelled(turn_id):
            return
        loaded = await _load_resume(turn_id)
        if loaded.status == "cancelled":
            return
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
                await MemoryStore().rollback(turn_id)
                await self._persist_cancelled(turn_id, started, job, agent, bot, stored=stored)
            elif outcome.approvals:
                await self._persist_waiting(
                    turn_id, started, job, agent, bot, outcome, stored=stored
                )
            else:
                await self._persist_done(turn_id, started, job, agent, bot, outcome, stored=stored)
        except Exception:
            await MemoryStore().rollback(turn_id)
            raise
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
            turn_id=turn_id,
            message_history=history,
            approvals=decisions,
            ephemeral=job.origin == "chit_chat",
        )
        parts: list[str] = []
        finished: RuntimeEvent | None = None
        error_code: str | None = None
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
            elif event.kind == "error" and error_code is None:
                error_code = event.code if event.code else "error"
        if finished is None or finished.model_messages is None:
            if self._watch is not None and self._watch.cancelled(turn_id):
                return _Outcome(text="", usage={}, model_messages=[], approvals=())
            if error_code is not None:
                # ``message`` can echo the prompt. Keep the code, store fixed text.
                logger.warning("runtime error {code}", code=error_code)
                raise TurnError(_failure_text("".join(parts)))
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
            if not await _has_user_message(session, turn_id):
                user = _user_message(turn_id, started, job, agent)
                session.add(user)
                events.append(_message_event(user))
            assistant = _assistant_message(turn_id, finished_at, agent, bot, outcome.text)
            session.add(assistant)
            events.append(_message_event(assistant))
            await _finish_job(session, job.id, "done", finished_at)
            agent_status = "done" if job.origin == "chit_chat" else "idle"
            await _set_agent(session, agent.id, agent_status, finished_at)
            events.append(_turn_event("turn.finished", turn_id, agent.id, "done"))
            events.append(_job_event("job.done", job.id, agent.id, "done"))
            events.append(_agent_event(agent.id, agent_status))
            for event in events:
                session.add(event)
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
                usage={},
                model_messages=None,
                finished_at=finished_at,
            )
            events: list[Event] = []
            if not await _has_user_message(session, turn_id):
                user = _user_message(turn_id, started, job, agent)
                session.add(user)
                events.append(_message_event(user))
            await _finish_job(session, job.id, "cancelled", finished_at)
            await _set_agent(session, agent.id, "idle", finished_at)
            events.append(_turn_event("turn.finished", turn_id, agent.id, "cancelled"))
            events.append(_job_event("job.done", job.id, agent.id, "cancelled"))
            events.append(_agent_event(agent.id, "idle"))
            events.extend(await _resolve_open_pendings(session, turn, finished_at))
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
        return _Job(
            id=row.id,
            bot_id=row.to_bot_id,
            agent_id=agent_id,
            text=row.text,
            origin=row.origin,
        )


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
            origin=job_row.origin,
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


async def _is_cancelled(session: AsyncSession, turn_id: str) -> bool:
    status = await session.scalar(select(TurnRow.status).where(TurnRow.id == turn_id))
    return status == "cancelled"


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
        await _set_agent(session, agent.id, "running", started)
        await session.commit()


async def _set_agent(session: AsyncSession, agent_id: str, status: str, when: datetime) -> None:
    from sevn.domain.agents import apply_lifecycle

    row = await session.get(AgentRow, agent_id)
    if row is None:
        return
    row.status = status
    row.last_activity_at = when
    apply_lifecycle(row, status, when)


_TERMINAL = frozenset({"done", "cancelled", "failed", "interrupted"})
_FAILED = "This turn failed."


def _failure_text(partial: str) -> str:
    """Chat text for a runtime error. Streamed text stays; the notice is fixed."""
    if partial == "":
        return _FAILED
    return f"{partial}\n{_FAILED}"


async def record_turn_failure(
    hub: Hub,
    exc: BaseException,
    *,
    job_id: str | None = None,
    turn_id: str | None = None,
) -> None:
    """Finish a turn that raised after it started, and show that to the client.

    A turn already committed as ``done`` or still paused on an open approval
    is left alone. Anything else becomes ``failed``, the job leaves the
    queue, and the agent returns to ``idle``.
    """
    notice = _failure_notice(exc)
    async with open_session() as session:
        job, turn = await _failure_rows(session, job_id, turn_id)
        if _leave_failure_alone(turn) or (
            turn is not None
            and turn.status == "waiting"
            and await _has_waiting_pending(session, turn.id)
        ):
            return
        now = utcnow()
        events: list[Event] = []
        if job is not None and job.status in {"queued", "started"}:
            job.status = "failed"
            job.finished_at = now
            if job.agent_id is not None:
                events.append(_job_event("job.done", job.id, job.agent_id, "failed"))
        if turn is not None and turn.status in {"running", "waiting"}:
            events.extend(await _fail_open_turn(session, turn, job, notice, now))
        agent_id = turn.agent_id if turn is not None else None
        if agent_id is None and job is not None:
            agent_id = job.agent_id
        if agent_id is not None:
            failed_id = turn.id if turn is not None else None
            status = await _sync_agent_status(session, agent_id, failed_id, now)
            if status is not None:
                events.append(_agent_event(agent_id, status))
        for event in events:
            session.add(event)
        await session.commit()
        for event in events:
            try:
                await hub.relay(event)
            except Exception:  # noqa: BLE001 — the row is committed; delivery can fail alone
                logger.exception("turn failure event was not delivered")


def _failure_notice(exc: BaseException) -> str:
    """Text safe to store. Provider errors can echo the prompt."""
    if isinstance(exc, ModelError | TurnError) and exc.message != "":
        return exc.message
    return _FAILED


def _leave_failure_alone(turn: TurnRow | None) -> bool:
    return turn is not None and turn.status in _TERMINAL


async def _failure_rows(
    session: AsyncSession,
    job_id: str | None,
    turn_id: str | None,
) -> tuple[JobRow | None, TurnRow | None]:
    turn = await session.get(TurnRow, turn_id) if turn_id is not None else None
    if job_id is None and turn is not None and len(turn.job_ids) > 0:
        job_id = turn.job_ids[0]
    job = await session.get(JobRow, job_id) if job_id is not None else None
    if turn is None and job is not None and job.agent_id is not None and job_id is not None:
        turn = await _open_turn_for_job(session, job.agent_id, job_id)
    return job, turn


async def _open_turn_for_job(session: AsyncSession, agent_id: str, job_id: str) -> TurnRow | None:
    rows = await session.scalars(
        select(TurnRow)
        .where(TurnRow.agent_id == agent_id)
        .where(TurnRow.status.in_(("running", "waiting")))
    )
    for row in rows:
        if job_id in row.job_ids:
            return row
    return None


async def _has_waiting_pending(session: AsyncSession, turn_id: str) -> bool:
    found = await session.scalar(
        select(PendingRow.id)
        .where(PendingRow.turn_id == turn_id)
        .where(PendingRow.status == "waiting")
        .limit(1)
    )
    return found is not None


async def _fail_open_turn(
    session: AsyncSession,
    turn: TurnRow,
    job: JobRow | None,
    notice: str,
    now: datetime,
) -> list[Event]:
    turn.status = "failed"
    turn.finished_at = now
    turn.model_messages = None
    events = await _resolve_open_pendings(session, turn, now)
    if job is not None and not await _has_user_message(session, turn.id):
        user = Message(
            id=new_id("msg_"),
            thread_id=turn.thread_id,
            turn_id=turn.id,
            agent_id=turn.agent_id,
            role="user",
            author="user",
            parts=_text_parts(job.text),
            created_at=turn.started_at,
        )
        session.add(user)
        events.append(_message_event(user))
    author = job.to_bot_id if job is not None else "system"
    assistant = Message(
        id=new_id("msg_"),
        thread_id=turn.thread_id,
        turn_id=turn.id,
        agent_id=turn.agent_id,
        role="assistant",
        author=author,
        parts=_text_parts(notice),
        created_at=now,
    )
    session.add(assistant)
    events.append(_message_event(assistant))
    events.append(_turn_event("turn.finished", turn.id, turn.agent_id, "failed"))
    return events


async def _resolve_open_pendings(
    session: AsyncSession,
    turn: TurnRow,
    now: datetime,
) -> list[Event]:
    rows = list(
        await session.scalars(
            select(PendingRow)
            .where(PendingRow.turn_id == turn.id)
            .where(PendingRow.status == "waiting")
        )
    )
    events: list[Event] = []
    answer: dict[str, object] = {"decision": "failed"}
    for row in rows:
        row.status = "resolved"
        row.answer = answer
        row.resolved_at = now
        payload: dict[str, object] = {
            "pending_id": row.id,
            "turn_id": row.turn_id,
            "agent_id": row.agent_id,
            "status": "resolved",
        }
        events.append(
            Event(type="pending.resolved", entity=row.id, payload=payload, created_at=now)
        )
    return events


async def persist_running_cancel(hub: Hub, turn_id: str) -> bool:
    """Store cancel for a turn whose model stream is still open.

    The in-memory flag is lost if the host stops. Recovery would otherwise
    mark the running turn failed and queue the same request again.
    Returns true when this call wrote ``cancelled``.
    """
    finished_at = utcnow()
    async with open_session() as session:
        turn = await session.get(TurnRow, turn_id)
        if turn is None or turn.status != "running":
            return False
        job_id = turn.job_ids[0] if len(turn.job_ids) > 0 else None
        job = await session.get(JobRow, job_id) if job_id is not None else None
        turn.status = "cancelled"
        turn.finished_at = finished_at
        turn.usage = {}
        turn.model_messages = None
        events: list[Event] = []
        if job is not None and not await _has_user_message(session, turn.id):
            user = Message(
                id=new_id("msg_"),
                thread_id=turn.thread_id,
                turn_id=turn.id,
                agent_id=turn.agent_id,
                role="user",
                author="user",
                parts=_text_parts(job.text),
                created_at=turn.started_at,
            )
            session.add(user)
            events.append(_message_event(user))
        for owned_id in turn.job_ids:
            await _finish_job(session, owned_id, "cancelled", finished_at)
        await _set_agent(session, turn.agent_id, "idle", finished_at)
        events.append(_turn_event("turn.finished", turn.id, turn.agent_id, "cancelled"))
        events.extend(
            _job_event("job.done", owned_id, turn.agent_id, "cancelled")
            for owned_id in turn.job_ids
        )
        events.append(_agent_event(turn.agent_id, "idle"))
        events.extend(await _resolve_open_pendings(session, turn, finished_at))
        for event in events:
            session.add(event)
        await session.commit()
        for event in events:
            await hub.relay(event)
    return True


async def cancel_persisted_waiting(hub: Hub, turn_id: str) -> bool:
    """Cancel a turn already stored as waiting.

    The stream that produced the approval has finished, so the in-memory
    cancel flag and ``Runtime.interrupt`` never reach it. Returns true when
    this call wrote ``cancelled``.
    """
    finished_at = utcnow()
    async with open_session() as session:
        turn = await session.get(TurnRow, turn_id)
        if turn is None or turn.status != "waiting":
            return False
        turn.status = "cancelled"
        turn.finished_at = finished_at
        turn.usage = {}
        turn.model_messages = None
        for job_id in turn.job_ids:
            await _finish_job(session, job_id, "cancelled", finished_at)
        await _set_agent(session, turn.agent_id, "idle", finished_at)
        events: list[Event] = [
            _turn_event("turn.finished", turn.id, turn.agent_id, "cancelled"),
        ]
        events.extend(
            _job_event("job.done", job_id, turn.agent_id, "cancelled") for job_id in turn.job_ids
        )
        events.append(_agent_event(turn.agent_id, "idle"))
        events.extend(await _resolve_open_pendings(session, turn, finished_at))
        for event in events:
            session.add(event)
        await session.commit()
        for event in events:
            await hub.relay(event)
    return True


async def _sync_agent_status(
    session: AsyncSession,
    agent_id: str,
    failed_turn_id: str | None,
    now: datetime,
) -> str | None:
    """Match the agent to any turn still open. Return the status when it changes."""
    await session.flush()
    stmt = (
        select(TurnRow.status)
        .where(TurnRow.agent_id == agent_id)
        .where(TurnRow.status.in_(("running", "waiting")))
    )
    if failed_turn_id is not None:
        stmt = stmt.where(TurnRow.id != failed_turn_id)
    open_status = set(await session.scalars(stmt))
    if "running" in open_status:
        desired = "running"
    elif "waiting" in open_status:
        desired = "waiting"
    else:
        desired = "idle"
    agent = await session.get(AgentRow, agent_id)
    if agent is None or agent.status == desired:
        return None
    agent.status = desired
    agent.last_activity_at = now
    return desired
