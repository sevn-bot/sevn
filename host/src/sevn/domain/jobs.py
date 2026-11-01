"""Queued jobs and cursor-paged messages (D2, D6, D10)."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select

from sevn.domain.errors import DomainError
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import Bot as BotRow
from sevn.store.models import Job as JobRow
from sevn.store.models import Message
from sevn.store.models import Thread as ThreadRow
from sevn.store.models import Turn as TurnRow

_PAGE = 50


class JobRecord(BaseModel):
    """One queued unit of work for an agent."""

    model_config = ConfigDict(extra="forbid")

    id: str
    bot_id: str
    agent_id: str
    text: str
    status: str


class MessageRecord(BaseModel):
    """One UI message returned by ``messages.list``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    thread_id: str
    turn_id: str
    agent_id: str
    role: str
    author: str
    parts: list[dict[str, str]]
    created_at: datetime


class MessagePage(BaseModel):
    """One page of messages, newest first."""

    model_config = ConfigDict(extra="forbid")

    messages: list[MessageRecord]
    next_cursor: str | None


class JobService:
    """Insert a job that the worker will claim."""

    async def enqueue(
        self,
        job_id: str,
        bot_id: str,
        agent_id: str,
        text: str,
        *,
        origin: str = "user",
        route_decision_id: str | None = None,
        status: str = "queued",
    ) -> JobRecord:
        now = utcnow()
        async with open_session() as session:
            session.add(
                JobRow(
                    id=job_id,
                    to_bot_id=bot_id,
                    agent_id=agent_id,
                    route_decision_id=route_decision_id,
                    origin=origin,
                    text=text,
                    attachments=[],
                    reply_to=None,
                    expects_reply=True,
                    hop=0,
                    status=status,
                    created_at=now,
                    started_at=None,
                    finished_at=None,
                )
            )
            await session.commit()
        return JobRecord(id=job_id, bot_id=bot_id, agent_id=agent_id, text=text, status=status)


async def page_messages(bot_id: str, cursor: str | None) -> MessagePage:
    """Return up to 50 messages for ``bot_id``, newest first.

    ``cursor`` is the id of the last message on the previous page.
    """
    async with open_session() as session:
        bot = await session.get(BotRow, bot_id)
        if bot is None:
            raise DomainError("not_found", "bot not found")
        stmt = (
            select(Message)
            .join(ThreadRow, Message.thread_id == ThreadRow.id)
            .where(ThreadRow.bot_id == bot_id)
        )
        if cursor is not None:
            anchor = await session.get(Message, cursor)
            if anchor is None:
                raise DomainError("invalid_params", "unknown cursor")
            thread = await session.get(ThreadRow, anchor.thread_id)
            if thread is None or thread.bot_id != bot_id:
                raise DomainError("invalid_params", "unknown cursor")
            stmt = stmt.where(
                or_(
                    Message.created_at < anchor.created_at,
                    and_(Message.created_at == anchor.created_at, Message.id < anchor.id),
                )
            )
        rows = list(
            await session.scalars(
                stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(_PAGE + 1)
            )
        )
    page = rows[:_PAGE]
    next_cursor = page[-1].id if len(rows) > _PAGE and page else None
    return MessagePage(messages=[_message(row) for row in page], next_cursor=next_cursor)


async def park_job(job_id: str, agent_id: str) -> None:
    """Queue ``job_id`` on ``agent_id``, preserving its original user message."""
    async with open_session() as session:
        job = await session.get(JobRow, job_id)
        if job is None:
            raise DomainError("not_found", "job not found")
        agent = await session.get(AgentRow, agent_id)
        if agent is None:
            raise DomainError("not_found", "agent not found")
        old_agent_id = job.agent_id
        job.agent_id = agent_id
        job.status = "queued"
        job.started_at = None
        job.finished_at = None
        turns = list(
            await session.scalars(
                select(TurnRow).where(
                    TurnRow.agent_id == old_agent_id,
                    TurnRow.status.in_(("queued", "cancelled")),
                )
            )
        )
        for turn in turns:
            if job_id not in turn.job_ids:
                continue
            messages = list(
                await session.scalars(
                    select(Message).where(Message.turn_id == turn.id, Message.role == "user")
                )
            )
            if turn.status == "cancelled":
                if not messages:
                    continue
                # Keep the cancelled attempt and its assistant output as history.
                # The rerouted job owns the same user message in a fresh turn.
                turn = TurnRow(
                    id=new_id("turn_"),
                    agent_id=agent_id,
                    thread_id=agent.thread_id,
                    job_ids=[job_id],
                    status="queued",
                    model=turn.model,
                    usage={},
                    model_messages=None,
                    started_at=utcnow(),
                    finished_at=None,
                )
                session.add(turn)
                await session.flush()
            else:
                turn.agent_id = agent_id
                turn.thread_id = agent.thread_id
            for message in messages:
                message.turn_id = turn.id
                message.agent_id = agent_id
                message.thread_id = agent.thread_id
        await session.commit()


def _message(row: Message) -> MessageRecord:
    return MessageRecord(
        id=row.id,
        thread_id=row.thread_id,
        turn_id=row.turn_id,
        agent_id=row.agent_id,
        role=row.role,
        author=row.author,
        parts=_parts(row.parts),
        created_at=row.created_at,
    )


def _parts(raw: list[object]) -> list[dict[str, str]]:
    parsed: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        body: dict[str, str] = {}
        for key, value in cast("dict[object, object]", item).items():
            if isinstance(key, str) and isinstance(value, str):
                body[key] = value
        if body:
            parsed.append(body)
    return parsed
