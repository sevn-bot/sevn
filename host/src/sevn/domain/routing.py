"""Placeholder routing (D6) and source-rule registration (D19).

Plan 0020 W3 replaces ``route_placeholder``. Plugins add rules here and do not
edit this module's rule list.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from sevn.decisions.base import RouteDecision
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


@dataclass(frozen=True, slots=True)
class RoutedMessage:
    """One message the decider chain can see. Persistence is a later wave."""

    text: str
    author: str
    created_at: datetime
    source: str
    new_agent: bool
    reply_to: str | None
    reply_to_agent_id: str | None
    agent_id: str | None


@dataclass(frozen=True, slots=True)
class OpenAgent:
    """An agent the router may target."""

    id: str
    title: str
    summary: str
    status: str


@dataclass(frozen=True, slots=True)
class PendingQuestion:
    """A question still waiting on one agent."""

    agent_id: str
    asked_at: datetime


@dataclass(frozen=True, slots=True)
class RouterContext:
    """Open lanes and recent user text for one routing decision."""

    bot_id: str
    open_agents: list[OpenAgent]
    pending_questions: list[PendingQuestion]
    recent_user_messages: dict[str, list[str]]
    runtime: str


type SourceRule = Callable[[RoutedMessage, RouterContext], RouteDecision | None]


@dataclass(frozen=True, slots=True)
class _RegisteredRule:
    source: str
    order: int
    seq: int
    rule: SourceRule


_rules: list[_RegisteredRule] = []
_seq = 0


def register_source_rule(source: str, rule: SourceRule, order: int) -> None:
    """Register a plugin rule for ``source``. Lower ``order`` runs first."""
    global _seq
    _seq += 1
    _rules.append(_RegisteredRule(source=source, order=order, seq=_seq, rule=rule))


def clear_source_rules() -> None:
    """Drop plugin rules. Tests use this so cases do not leak."""
    _rules.clear()


def source_rules(source: str) -> list[SourceRule]:
    """Plugin rules for ``source``, in order. Built-in rules are not included."""
    chosen = [item for item in _rules if item.source == source]
    chosen.sort(key=lambda item: (item.order, item.seq))
    return [item.rule for item in chosen]
