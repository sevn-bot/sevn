"""Placeholder routing (D6). Plan 0020 replaces ``route_placeholder``."""

from __future__ import annotations

from sqlalchemy import select

from sevn.domain.agents import AgentRecord, AgentService
from sevn.domain.errors import DomainError
from sevn.domain.session import open_session
from sevn.store.models import Agent as AgentRow

_OPEN = ("running", "waiting", "idle")


async def route_placeholder(
    bot_id: str,
    *,
    text: str,
    agent_id: str | None = None,
    new_agent: bool = False,
    origin_job_id: str | None = None,
) -> AgentRecord:
    """Choose the agent for one message.

    An explicit ``agent_id`` is that lane. ``new_agent`` starts another lane.
    Otherwise the bot's most recent ``running``, ``waiting``, or ``idle`` agent
    is used, and a new agent starts when none is open. ``text`` is accepted so
    the plan 0020 replacement can read the message; this rule does not.
    """
    _ = text
    if agent_id is not None:
        return await _named(bot_id, agent_id)
    if new_agent:
        return await AgentService().spawn(bot_id, origin_job_id=origin_job_id)
    latest = await _latest_open(bot_id)
    if latest is not None:
        return latest
    return await AgentService().spawn(bot_id, origin_job_id=origin_job_id)


async def _named(bot_id: str, agent_id: str) -> AgentRecord:
    agent = await AgentService().get(agent_id)
    if agent.bot_id != bot_id:
        raise DomainError("not_found", "agent not found")
    return agent


async def _latest_open(bot_id: str) -> AgentRecord | None:
    async with open_session() as session:
        agent_id = await session.scalar(
            select(AgentRow.id)
            .where(AgentRow.bot_id == bot_id)
            .where(AgentRow.status.in_(_OPEN))
            .order_by(AgentRow.last_activity_at.desc(), AgentRow.created_at.desc())
            .limit(1)
        )
    if agent_id is None:
        return None
    return await AgentService().get(agent_id)
