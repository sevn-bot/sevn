"""Turn persistence helpers: message parts, outbox events and row updates."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.domain.agents import AgentRecord
from sevn.domain.bots import BotRecord
from sevn.domain.ids import new_id
from sevn.runtime.errors import TurnError
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import Event, Message
from sevn.store.models import Job as JobRow
from sevn.store.models import PendingRequest as PendingRow
from sevn.store.models import Turn as TurnRow


def text_parts(text: str) -> list[object]:
    part: dict[str, object] = {"type": "text", "text": text}
    return [part]


def assistant_message(
    turn_id: str,
    finished_at: datetime,
    agent: AgentRecord,
    bot: BotRecord,
    text: str,
    extra: list[dict[str, str]] | None = None,
) -> Message:
    parts = text_parts(text)
    if extra:
        parts.extend(extra)
    return Message(
        id=new_id("msg_"),
        thread_id=agent.thread_id,
        turn_id=turn_id,
        agent_id=agent.id,
        role="assistant",
        author=bot.id,
        parts=parts,
        created_at=finished_at,
    )


def message_event(message: Message) -> Event:
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


def turn_event(event_type: str, turn_id: str, agent_id: str, status: str) -> Event:
    payload: dict[str, object] = {
        "turn_id": turn_id,
        "agent_id": agent_id,
        "status": status,
    }
    return Event(type=event_type, entity=turn_id, payload=payload, created_at=utcnow())


def job_event(event_type: str, job_id: str, agent_id: str, status: str) -> Event:
    payload: dict[str, object] = {"job_id": job_id, "agent_id": agent_id, "status": status}
    return Event(type=event_type, entity=job_id, payload=payload, created_at=utcnow())


def agent_event(agent_id: str, status: str) -> Event:
    payload: dict[str, object] = {"agent_id": agent_id, "status": status}
    return Event(type="agent.updated", entity=agent_id, payload=payload, created_at=utcnow())


def pending_event(row: PendingRow) -> Event:
    payload: dict[str, object] = {
        "pending_id": row.id,
        "turn_id": row.turn_id,
        "agent_id": row.agent_id,
        "kind": row.kind,
    }
    return Event(type="pending.created", entity=row.id, payload=payload, created_at=utcnow())


async def set_agent(session: AsyncSession, agent_id: str, status: str, when: datetime) -> None:
    from sevn.domain.agents import apply_lifecycle

    row = await session.get(AgentRow, agent_id)
    if row is None:
        return
    row.status = status
    row.last_activity_at = when
    apply_lifecycle(row, status, when)


async def finish_job(session: AsyncSession, job_id: str, status: str, when: datetime) -> None:
    row = await session.get(JobRow, job_id)
    if row is None:
        raise TurnError("job not found")
    row.status = status
    row.finished_at = when


async def has_user_message(session: AsyncSession, turn_id: str) -> bool:
    found = await session.scalar(
        select(Message.id).where(Message.turn_id == turn_id, Message.role == "user").limit(1)
    )
    return found is not None


async def resolve_open_pendings(
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
