"""Startup sweep for turns that died mid-run (D7, D8)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.log import logger
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import Event, Message
from sevn.store.models import Job as JobRow
from sevn.store.models import PendingRequest as PendingRow
from sevn.store.models import Turn as TurnRow

_RESEND = "This Claude turn was interrupted. Resend your message."


async def recover() -> list[str]:
    """Requeue ``started`` jobs whose turn has no committed result.

    A ``waiting`` Pydantic AI turn stays waiting, and so does its job. A
    committed ``model_messages`` value is a result, including an empty list.
    A Claude turn that was blocked on ``can_use_tool`` only holds that wait in
    memory, so a restart marks the turn ``interrupted`` and asks the user to
    resend.

    The crashed attempt's running turn is marked ``failed`` so the retry is
    not a second running turn for the same job. The returned agent ids own a
    queued job; the caller starts a pump for each of them.
    """
    async with open_session() as session:
        jobs = list(await session.scalars(select(JobRow).where(JobRow.status == "started")))
        if len(jobs) > 0:
            turns = list(await session.scalars(select(TurnRow)))
            pendings = list(
                await session.scalars(select(PendingRow).where(PendingRow.status == "waiting"))
            )
            waiting_ids = {row.turn_id for row in pendings}
            now = utcnow()
            for job in jobs:
                related = [turn for turn in turns if job.id in turn.job_ids]
                if await _interrupt_claude(session, job, related, pendings, waiting_ids):
                    continue
                if any(turn.status == "waiting" for turn in related):
                    continue
                if any(turn.model_messages is not None for turn in related):
                    continue
                _close_crashed_turns(session, related, now)
                job.status = "queued"
                job.started_at = None
                await _idle_crashed_agent(session, turns, job.agent_id, now)
                logger.info("requeued crashed job {job_id}", job_id=job.id)
            await session.commit()
    return await _queued_agent_ids()


def _close_crashed_turns(session: AsyncSession, related: list[TurnRow], now: datetime) -> None:
    """Close the crashed attempt so the retry is the only running turn."""
    for turn in related:
        if turn.status != "running":
            continue
        turn.status = "failed"
        turn.finished_at = now
        session.add(_turn_finished(turn.id, turn.agent_id, now))


async def _idle_crashed_agent(
    session: AsyncSession,
    turns: list[TurnRow],
    agent_id: str | None,
    now: datetime,
) -> None:
    if agent_id is None:
        return
    if any(turn.agent_id == agent_id and turn.status in {"running", "waiting"} for turn in turns):
        return
    agent = await session.get(AgentRow, agent_id)
    if agent is None or agent.status != "running":
        return
    agent.status = "idle"
    agent.last_activity_at = now
    session.add(_agent_updated(agent_id, now))


def _turn_finished(turn_id: str, agent_id: str, now: datetime) -> Event:
    payload: dict[str, object] = {
        "turn_id": turn_id,
        "agent_id": agent_id,
        "status": "failed",
    }
    return Event(type="turn.finished", entity=turn_id, payload=payload, created_at=now)


def _agent_updated(agent_id: str, now: datetime) -> Event:
    payload: dict[str, object] = {"agent_id": agent_id, "status": "idle"}
    return Event(type="agent.updated", entity=agent_id, payload=payload, created_at=now)


async def _queued_agent_ids() -> list[str]:
    async with open_session() as session:
        found = await session.scalars(
            select(JobRow.agent_id)
            .where(JobRow.status == "queued")
            .where(JobRow.agent_id.is_not(None))
            .distinct()
        )
    return [agent_id for agent_id in found if isinstance(agent_id, str)]


async def _interrupt_claude(
    session: AsyncSession,
    job: JobRow,
    related: list[TurnRow],
    pendings: list[PendingRow],
    waiting_ids: set[str],
) -> bool:
    """Mark a Claude turn that cannot be resumed. The caller commits."""
    agent_id = job.agent_id
    if agent_id is None:
        return False
    agent = await session.get(AgentRow, agent_id)
    if agent is None or agent.runtime != "claude":
        return False
    stalled = [turn for turn in related if turn.status == "waiting" or turn.id in waiting_ids]
    if len(stalled) == 0:
        return False
    now = utcnow()
    for turn in stalled:
        turn.status = "interrupted"
        turn.finished_at = now
        message = _resend_message(turn, job.to_bot_id, now)
        session.add(message)
        session.add(_message_event(message, now))
        for pending in pendings:
            if pending.turn_id != turn.id or pending.status != "waiting":
                continue
            pending.status = "resolved"
            pending.answer = {"decision": "interrupted"}
            pending.resolved_at = now
    job.status = "cancelled"
    job.finished_at = now
    agent.status = "idle"
    agent.last_activity_at = now
    return True


def _resend_message(turn: TurnRow, bot_id: str, now: datetime) -> Message:
    parts: list[object] = [{"type": "text", "text": _RESEND}]
    return Message(
        id=new_id("msg_"),
        thread_id=turn.thread_id,
        turn_id=turn.id,
        agent_id=turn.agent_id,
        role="assistant",
        author=bot_id,
        parts=parts,
        created_at=now,
    )


def _message_event(message: Message, now: datetime) -> Event:
    payload: dict[str, object] = {
        "message_id": message.id,
        "thread_id": message.thread_id,
        "turn_id": message.turn_id,
        "agent_id": message.agent_id,
        "role": message.role,
        "parts": message.parts,
    }
    return Event(type="message.created", entity=message.id, payload=payload, created_at=now)
