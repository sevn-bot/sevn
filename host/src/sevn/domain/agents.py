"""Agents and the thread each one owns (D1, D2).

``AgentRecord`` is the name of this model so it does not clash with
``pydantic_ai.Agent``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from sevn.contracts.kinds import AgentStatus, RuntimeName
from sevn.domain.errors import DomainError
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import Bot as BotRow
from sevn.store.models import Job as JobRow
from sevn.store.models import Thread as ThreadRow

_STATUSES = frozenset({"running", "waiting", "idle", "done", "archived"})
_OPEN = frozenset({"running", "waiting", "idle"})
_OCCUPYING = frozenset({"running", "waiting"})
_IDLE_TTL = timedelta(hours=24)
_ARCHIVE_AFTER = timedelta(days=7)
_SIBLING_LIMIT = 10


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
            apply_lifecycle(agent, "idle", now)
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
            now = utcnow()
            row.status = status
            row.last_activity_at = now
            apply_lifecycle(row, status, now)
            await session.commit()
            return _record(row)

    async def revive(self, agent_id: str) -> AgentRecord:
        """A follow-up opens a done or archived agent on the same thread (D8)."""
        agent = await self.get(agent_id)
        if agent.status == "done" or agent.status == "archived":
            return await self.set_status(agent_id, "idle")
        return agent


def apply_lifecycle(row: AgentRow, status: str, when: datetime) -> None:
    """Keep idle and archive clocks aligned with ``status``."""
    if status == "idle":
        row.idle_since = when
    else:
        row.idle_since = None
    if status == "archived":
        if row.archived_at is None:
            row.archived_at = when
    elif status != "done":
        row.archived_at = None


async def sibling_block(bot_id: str, agent_id: str) -> str:
    """Titles and statuses of up to ten other open agents (D8)."""
    agents = await AgentService().list(bot_id)
    others = [agent for agent in agents if agent.id != agent_id and agent.status in _OPEN]
    chosen = others[-_SIBLING_LIMIT:]
    if len(chosen) == 0:
        return ""
    lines = [f"- {agent.title} ({agent.status})" for agent in chosen]
    return "Siblings:\n" + "\n".join(lines)


async def occupying(bot_id: str) -> int:
    """Agents of ``bot_id`` that currently hold a parallel slot."""
    async with open_session() as session:
        rows = list(
            await session.scalars(
                select(AgentRow.id)
                .where(AgentRow.bot_id == bot_id)
                .where(AgentRow.status.in_(_OCCUPYING))
            )
        )
    return len(rows)


async def queued_agent_ids(bot_id: str) -> list[str]:
    """Agents with a queued job, oldest job first."""
    async with open_session() as session:
        rows = list(
            await session.scalars(
                select(JobRow.agent_id)
                .where(JobRow.to_bot_id == bot_id)
                .where(JobRow.status == "queued")
                .order_by(JobRow.created_at, JobRow.id)
            )
        )
    found: list[str] = []
    for agent_id in rows:
        if agent_id is None or agent_id in found:
            continue
        found.append(agent_id)
    return found


async def expire_agents() -> None:
    """Idle agents become done after 24 h, and done agents archive after 7 days."""
    now = utcnow()
    async with open_session() as session:
        rows = list(
            await session.scalars(select(AgentRow).where(AgentRow.status.in_(("idle", "done"))))
        )
        for row in rows:
            idle_for = row.idle_since or row.last_activity_at
            if row.status == "idle" and _due(idle_for, _IDLE_TTL, now):
                row.status = "done"
                row.idle_since = None
                row.last_activity_at = now
            elif (
                row.status == "done"
                and row.archived_at is None
                and _due(row.last_activity_at, _ARCHIVE_AFTER, now)
            ):
                row.status = "archived"
                row.archived_at = now
        await session.commit()


def _due(since: datetime | None, wait: timedelta, now: datetime) -> bool:
    if since is None:
        return False
    return _stamp(since) + wait.total_seconds() <= _stamp(now)


def _stamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


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
