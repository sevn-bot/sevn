"""Agents and the thread each one owns (D1, D2).

``AgentRecord`` is the name of this model so it does not clash with
``pydantic_ai.Agent``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from sevn.contracts.kinds import AgentStatus, RuntimeName
from sevn.domain.errors import DomainError
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import Bot as BotRow
from sevn.store.models import Thread as ThreadRow

_STATUSES = frozenset({"running", "waiting", "idle", "done", "archived"})


class AgentRecord(BaseModel):
    """One agent and the thread it owns."""

    model_config = ConfigDict(extra="forbid")

    id: str
    bot_id: str
    thread_id: str
    title: str
    summary: str
    status: AgentStatus
    runtime: RuntimeName
    runtime_session_ref: str | None
    origin_job_id: str | None
    isolation: str
    created_at: datetime
    last_activity_at: datetime


class AgentService:
    """Spawn an agent for a bot, and read or update its status."""

    async def spawn(
        self,
        bot_id: str,
        *,
        origin_job_id: str | None = None,
    ) -> AgentRecord:
        async with open_session() as session:
            bot = await session.get(BotRow, bot_id)
            if bot is None:
                raise DomainError("not_found", "bot not found")
            now = utcnow()
            agent_id = new_id("agent_")
            thread_id = new_id("thread_")
            agent = AgentRow(
                id=agent_id,
                bot_id=bot_id,
                thread_id=thread_id,
                title="",
                summary="",
                status="idle",
                runtime=bot.runtime,
                runtime_session_ref=None,
                origin_job_id=origin_job_id,
                isolation="shared",
                created_at=now,
                last_activity_at=now,
            )
            session.add(agent)
            await session.flush()
            session.add(
                ThreadRow(
                    id=thread_id,
                    bot_id=bot_id,
                    agent_id=agent_id,
                    kind="agent",
                    summary="",
                    summary_upto=None,
                )
            )
            await session.commit()
            return _record(agent)

    async def get(self, agent_id: str) -> AgentRecord:
        async with open_session() as session:
            row = await session.get(AgentRow, agent_id)
            if row is None:
                raise DomainError("not_found", "agent not found")
            return _record(row)

    async def list(self, bot_id: str) -> list[AgentRecord]:
        async with open_session() as session:
            bot = await session.get(BotRow, bot_id)
            if bot is None:
                raise DomainError("not_found", "bot not found")
            rows = list(
                await session.scalars(
                    select(AgentRow).where(AgentRow.bot_id == bot_id).order_by(AgentRow.created_at)
                )
            )
            return [_record(row) for row in rows]

    async def set_status(self, agent_id: str, status: str) -> AgentRecord:
        if status not in _STATUSES:
            raise DomainError("invalid_params", "unknown agent status")
        async with open_session() as session:
            row = await session.get(AgentRow, agent_id)
            if row is None:
                raise DomainError("not_found", "agent not found")
            row.status = status
            row.last_activity_at = utcnow()
            await session.commit()
            return _record(row)


def _record(row: AgentRow) -> AgentRecord:
    return AgentRecord(
        id=row.id,
        bot_id=row.bot_id,
        thread_id=row.thread_id,
        title=row.title,
        summary=row.summary,
        status=_status(row.status),
        runtime=_runtime(row.runtime),
        runtime_session_ref=row.runtime_session_ref,
        origin_job_id=row.origin_job_id,
        isolation=row.isolation,
        created_at=row.created_at,
        last_activity_at=row.last_activity_at,
    )


def _status(value: str) -> AgentStatus:
    if (
        value == "running"
        or value == "waiting"
        or value == "idle"
        or value == "done"
        or value == "archived"
    ):
        return value
    raise DomainError("invalid_params", "unknown agent status")


def _runtime(value: str) -> RuntimeName:
    if value == "pydantic_ai" or value == "claude":
        return value
    raise DomainError("invalid_params", "unknown runtime")
