"""TurnRunner: stream one job, coalesce ticks, and commit the turn (D4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from sevn.domain.agents import AgentRecord, AgentService
from sevn.domain.bots import BotRecord, BotService
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.log import logger
from sevn.protocol.hub import Hub
from sevn.runtime.base import Runtime, TurnContext
from sevn.runtime.errors import TurnError
from sevn.runtime.events import RuntimeEvent
from sevn.store.db import utcnow
from sevn.store.models import Event, Message
from sevn.store.models import Job as JobRow
from sevn.store.models import Turn as TurnRow


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


class TurnRunner:
    """Drive one runtime turn and persist it in a single end transaction."""

    def __init__(self, hub: Hub, runtime: Runtime) -> None:
        self._hub = hub
        self._runtime = runtime

    async def run(self, job_id: str) -> None:
        job = await _mark_started(job_id)
        agent = await AgentService().get(job.agent_id)
        bot = await BotService().get(job.bot_id)
        history = await _previous_messages(agent.id)
        turn_id = new_id("turn_")
        started = utcnow()
        with logger.contextualize(bot_id=bot.id, agent_id=agent.id, turn_id=turn_id):
            logger.info("turn started")
            await self._runtime.open(agent)
            try:
                outcome = await self._drive(turn_id, agent, bot, job, history)
                await self._persist(turn_id, started, job, agent, bot, outcome)
            finally:
                await self._runtime.close(agent.id)
            logger.info("turn finished")

    async def _drive(
        self,
        turn_id: str,
        agent: AgentRecord,
        bot: BotRecord,
        job: _Job,
        history: list[object] | None,
    ) -> _Outcome:
        context = TurnContext(
            agent=agent,
            bot=bot,
            job_id=job.id,
            text=job.text,
            message_history=history,
        )
        parts: list[str] = []
        finished: RuntimeEvent | None = None
        async for event in self._runtime.run_turn(context):
            if event.kind == "text_delta" and event.text:
                parts.append(event.text)
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
        return _Outcome(text=text, usage=usage, model_messages=finished.model_messages)

    async def _persist(
        self,
        turn_id: str,
        started: datetime,
        job: _Job,
        agent: AgentRecord,
        bot: BotRecord,
        outcome: _Outcome,
    ) -> None:
        finished_at = utcnow()
        user_parts = _text_parts(job.text)
        assistant_parts = _text_parts(outcome.text)
        async with open_session() as session:
            session.add(
                TurnRow(
                    id=turn_id,
                    agent_id=agent.id,
                    thread_id=agent.thread_id,
                    job_ids=[job.id],
                    status="done",
                    model=bot.model,
                    usage=outcome.usage,
                    model_messages=outcome.model_messages,
                    started_at=started,
                    finished_at=finished_at,
                )
            )
            await session.flush()
            user = Message(
                id=new_id("msg_"),
                thread_id=agent.thread_id,
                turn_id=turn_id,
                agent_id=agent.id,
                role="user",
                author="user",
                parts=user_parts,
                created_at=started,
            )
            assistant = Message(
                id=new_id("msg_"),
                thread_id=agent.thread_id,
                turn_id=turn_id,
                agent_id=agent.id,
                role="assistant",
                author=bot.id,
                parts=assistant_parts,
                created_at=finished_at,
            )
            session.add(user)
            session.add(assistant)
            row = await session.get(JobRow, job.id)
            if row is None:
                raise TurnError("job not found")
            row.status = "done"
            row.finished_at = finished_at
            events = (
                _message_event(user),
                _message_event(assistant),
                _turn_event(turn_id, agent.id),
            )
            for event in events:
                session.add(event)
            await session.commit()
            for event in events:
                await self._hub.relay(event)


def _text_parts(text: str) -> list[object]:
    part: dict[str, object] = {"type": "text", "text": text}
    return [part]


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


def _turn_event(turn_id: str, agent_id: str) -> Event:
    payload: dict[str, object] = {
        "turn_id": turn_id,
        "agent_id": agent_id,
        "status": "done",
    }
    return Event(
        type="turn.finished",
        entity=turn_id,
        payload=payload,
        created_at=utcnow(),
    )


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
