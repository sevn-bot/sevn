"""Startup sweep for turns that died mid-run (D7, D8)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import Event, Message
from sevn.store.models import Job as JobRow
from sevn.store.models import PendingRequest as PendingRow
from sevn.store.models import Turn as TurnRow

_RESEND = "This Claude turn was interrupted. Resend your message."


async def recover() -> None:
    """Requeue ``started`` jobs whose turn has no committed result.

    A ``waiting`` Pydantic AI turn stays waiting, and so does its job. A
    committed ``model_messages`` value is a result, including an empty list.
    A Claude turn that was blocked on ``can_use_tool`` only holds that wait in
    memory, so a restart marks the turn ``interrupted`` and asks the user to
    resend.
    """
    async with open_session() as session:
        jobs = list(await session.scalars(select(JobRow).where(JobRow.status == "started")))
        if len(jobs) == 0:
            return
        turns = list(await session.scalars(select(TurnRow)))
        pendings = list(
            await session.scalars(select(PendingRow).where(PendingRow.status == "waiting"))
        )
        waiting_ids = {row.turn_id for row in pendings}
        for job in jobs:
            related = [turn for turn in turns if job.id in turn.job_ids]
            if await _interrupt_claude(session, job, related, pendings, waiting_ids):
                continue
            if any(turn.status == "waiting" for turn in related):
                continue
            if any(turn.model_messages is not None for turn in related):
                continue
            job.status = "queued"
            job.started_at = None
        await session.commit()


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
