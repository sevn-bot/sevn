"""Queued jobs and cursor-paged messages (D2, D6, D10)."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select

from sevn.domain.errors import DomainError
from sevn.domain.session import open_session
from sevn.store.db import utcnow
from sevn.store.models import Bot as BotRow
from sevn.store.models import Job as JobRow
from sevn.store.models import Message
from sevn.store.models import Thread as ThreadRow

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

    async def enqueue(self, job_id: str, bot_id: str, agent_id: str, text: str) -> JobRecord:
        now = utcnow()
        async with open_session() as session:
            session.add(
                JobRow(
                    id=job_id,
                    to_bot_id=bot_id,
                    agent_id=agent_id,
                    route_decision_id=None,
                    origin="user",
                    text=text,
                    attachments=[],
                    reply_to=None,
                    expects_reply=True,
                    hop=0,
                    status="queued",
                    created_at=now,
                    started_at=None,
                    finished_at=None,
                )
            )
            await session.commit()
        return JobRecord(id=job_id, bot_id=bot_id, agent_id=agent_id, text=text, status="queued")


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
