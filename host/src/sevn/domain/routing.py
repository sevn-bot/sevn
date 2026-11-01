"""Message routing and source-rule registration (D3, D5, D19).

Plugins add rules here and do not edit this module's rule list.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.config import Settings
from sevn.decisions.base import RouteDecision
from sevn.decisions.log import last_decision_id, mark_corrected
from sevn.domain.agents import AgentRecord, AgentService, apply_lifecycle, lane_text, occupying
from sevn.domain.bots import BotRecord, BotService
from sevn.domain.errors import DomainError
from sevn.domain.ids import new_id
from sevn.domain.jobs import JobService, park_job
from sevn.domain.session import open_session
from sevn.log import logger
from sevn.protocol.hub import Hub
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import Job as JobRow
from sevn.store.models import Message, RouteDecisionRow
from sevn.store.models import PendingRequest as PendingRow
from sevn.store.models import Turn as TurnRow

_OPEN = ("running", "waiting", "idle")
_ENDED_JOBS = frozenset({"done", "failed", "cancelled"})
_QUEUED_ON_TARGET = frozenset({"follow_up", "steer"})
_SLOT_HOLDERS = frozenset({"running", "waiting"})
_FRESH = frozenset({"new_request", "chit_chat"})


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
    bot_id: str = ""


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


async def route(message: RoutedMessage, source: str) -> RouteDecision:
    """Rules, then jev, then the gate and fallback chain (D3, D4)."""
    from sevn.decisions.registry import decide

    routed = RoutedMessage(
        text=message.text,
        author=message.author,
        created_at=message.created_at,
        source=source,
        new_agent=message.new_agent,
        reply_to=message.reply_to,
        reply_to_agent_id=message.reply_to_agent_id,
        agent_id=message.agent_id,
        bot_id=message.bot_id,
    )
    if routed.bot_id == "":
        raise DomainError("invalid_params", "bot_id is required")
    context = await _load_context(routed.bot_id)
    return await decide(routed, context)


async def deliver(
    message: RoutedMessage,
    source: str,
    *,
    job_id: str,
    hub: Hub,
) -> tuple[str, str]:
    """Route ``message`` and enqueue the job the decision asks for."""
    before = last_decision_id()
    decision = await route(message, source)
    after = last_decision_id()
    decision_id = after if after != before else None
    bot = await BotService().get(message.bot_id)
    agent, origin, consumed = await _act(message, decision, job_id)
    held = await _over_cap(bot.id, decision.intent, agent)
    job_status = "waiting" if decision.ask_user else ("done" if consumed else "queued")
    await JobService().enqueue(
        job_id,
        bot.id,
        agent.id,
        message.text,
        origin=origin,
        route_decision_id=decision_id,
        status=job_status,
    )
    message_id = await _attach_user_message(job_id, agent, bot, message.text, decision)
    payload: dict[str, object] = {
        "job_id": job_id,
        "agent_id": agent.id,
        "bot_id": bot.id,
        "status": job_status,
    }
    if held:
        ahead = await _ahead(bot.id, job_id)
        payload["ahead"] = ahead
        payload["notice"] = f"queued: {ahead} ahead"
    await hub.emit(
        "route.decided",
        message_id,
        {
            "message_id": message_id,
            "job_id": job_id,
            "agent_id": agent.id,
            "bot_id": bot.id,
            "intent": decision.intent,
            "path": decision.path,
        },
    )
    await hub.emit("job.queued", job_id, payload)
    logger.info("route decided {intent} via {path}", intent=decision.intent, path=decision.path)
    if not held and not consumed and not decision.ask_user:
        await _start(agent.id)
    return job_id, agent.id


async def reroute(
    message_id: str,
    *,
    agent_id: str | None,
    start_new: bool,
    hub: Hub,
) -> tuple[str, str]:
    """Move a message's job, cancelling a running turn first (D7)."""
    job_id, bot_id, decision_id, job_status = await _job_for_message(message_id)
    if job_status in _ENDED_JOBS:
        # Moving an ended job would run the message (and its side effects) again.
        raise DomainError("invalid_params", "message already finished")
    if start_new:
        target = await AgentService().spawn(bot_id, origin_job_id=job_id)
    else:
        if agent_id is None:
            raise DomainError("invalid_params", "agent_id or new is required")
        target = await _agent_on_bot(bot_id, agent_id)
    await _requeue(job_id, target.id)
    await _start(target.id)
    await mark_corrected(decision_id, target.id)
    await hub.emit(
        "route.corrected",
        message_id,
        {"message_id": message_id, "job_id": job_id, "agent_id": target.id},
    )
    return job_id, target.id


async def _act(
    message: RoutedMessage, decision: RouteDecision, job_id: str
) -> tuple[AgentRecord, str, bool]:
    """Choose the lane. ``consumed`` means the message must not run as a job."""
    if decision.ask_user:
        agent = await _first_open(message.bot_id)
        if agent is None:
            agent = await _spawn(message, job_id)
        return agent, "user", False
    if decision.intent in _FRESH or decision.target_agent_id is None:
        agent = await _spawn(message, job_id)
        origin = "chit_chat" if decision.intent == "chit_chat" else "user"
        return agent, origin, False
    agent = await _agent_on_bot(message.bot_id, decision.target_agent_id)
    if decision.intent == "follow_up":
        return await AgentService().revive(agent.id), "user", False
    if decision.intent == "steer":
        steered = await _steer(agent.id, message.text)
        if not steered:
            logger.info("steer queued for {runtime}", runtime=agent.runtime)
        return agent, "user", steered
    if decision.intent == "answer":
        await _resolve_answer(agent.id, message.text)
        return agent, "user", False
    if decision.intent == "cancel":
        await _cancel_agent(agent.id)
        return agent, "user", True
    return agent, "user", False


async def _over_cap(bot_id: str, intent: str, agent: AgentRecord) -> bool:
    """True when running this job would take a parallel slot the bot does not have.

    A new lane always needs a slot. A follow-up or a queued steer needs one
    only when its target is not already running or waiting.
    """
    if intent in _FRESH:
        pass
    elif intent in _QUEUED_ON_TARGET:
        if agent.status in _SLOT_HOLDERS:
            return False
    else:
        return False
    return await occupying(bot_id) >= Settings.load().bots.max_parallel_agents


async def _start(agent_id: str) -> None:
    from sevn.runtime.worker import current

    worker = current()
    if worker is None:
        return
    worker.kick(agent_id)
    await worker.settle(agent_id)


async def _steer(agent_id: str, text: str) -> bool:
    from sevn.runtime.worker import current

    worker = current()
    if worker is None:
        return False
    return await worker.steer(agent_id, text)


async def _requeue(job_id: str, agent_id: str) -> None:
    from sevn.runtime.worker import current

    worker = current()
    if worker is not None:
        await worker.interrupt_and_requeue(job_id, agent_id)
        return
    await park_job(job_id, agent_id)


async def _cancel_agent(agent_id: str) -> None:
    from sevn.runtime.worker import current

    turn_id = await _running_turn(agent_id)
    worker = current()
    if worker is not None and turn_id is not None:
        await worker.cancel(turn_id)
    await AgentService().set_status(agent_id, "done")


async def _resolve_answer(agent_id: str, text: str) -> None:
    now = utcnow()
    answer: dict[str, object] = {"text": text}
    async with open_session() as session:
        rows = list(
            await session.scalars(
                select(PendingRow)
                .where(PendingRow.agent_id == agent_id)
                .where(PendingRow.status == "waiting")
                .where(PendingRow.kind == "question")
            )
        )
        for row in rows:
            row.status = "resolved"
            row.answer = answer
            row.resolved_at = now
        # Close the paused turn and its job. The answer is delivered as the
        # next user message by ``deliver``; leaving the turn waiting wedges
        # the agent because ``Worker._pump`` returns while a turn is waiting.
        waiting_turns = list(
            await session.scalars(
                select(TurnRow)
                .where(TurnRow.agent_id == agent_id)
                .where(TurnRow.status == "waiting")
            )
        )
        for turn in waiting_turns:
            turn.status = "done"
            turn.finished_at = now
            for job_id in turn.job_ids or ():
                job = await session.get(JobRow, job_id)
                if job is not None and job.status in ("queued", "started"):
                    job.status = "done"
                    job.finished_at = now
        await session.flush()
        agent = await session.get(AgentRow, agent_id)
        if agent is not None and agent.status == "waiting":
            still = await session.scalar(
                select(PendingRow.id)
                .where(PendingRow.agent_id == agent_id)
                .where(PendingRow.status == "waiting")
                .limit(1)
            )
            if still is None:
                agent.status = "idle"
                agent.last_activity_at = now
                apply_lifecycle(agent, "idle", now)
        await session.commit()


async def _agent_on_bot(bot_id: str, agent_id: str) -> AgentRecord:
    agent = await AgentService().get(agent_id)
    if agent.bot_id != bot_id:
        raise DomainError("not_found", "agent not found")
    return agent


async def _first_open(bot_id: str) -> AgentRecord | None:
    async with open_session() as session:
        agent_id = await session.scalar(
            select(AgentRow.id)
            .where(AgentRow.bot_id == bot_id)
            .where(AgentRow.status.in_(_OPEN))
            .order_by(AgentRow.created_at)
            .limit(1)
        )
    if agent_id is None:
        return None
    return await AgentService().get(agent_id)


async def _load_context(bot_id: str) -> RouterContext:
    bot = await BotService().get(bot_id)
    async with open_session() as session:
        agents = list(
            await session.scalars(
                select(AgentRow)
                .where(AgentRow.bot_id == bot_id)
                .where(AgentRow.status.in_(_OPEN))
                .order_by(AgentRow.created_at)
            )
        )
        agent_ids = [agent.id for agent in agents]
        pending = await _questions(session, agent_ids)
        recent = await _recent(session, agent_ids)
    return RouterContext(
        bot_id=bot_id,
        open_agents=[
            OpenAgent(id=agent.id, title=agent.title, summary=agent.summary, status=agent.status)
            for agent in agents
        ],
        pending_questions=pending,
        recent_user_messages=recent,
        runtime=bot.runtime,
    )


async def _questions(session: AsyncSession, agent_ids: list[str]) -> list[PendingQuestion]:
    if len(agent_ids) == 0:
        return []
    rows = list(
        await session.scalars(
            select(PendingRow)
            .where(PendingRow.agent_id.in_(agent_ids))
            .where(PendingRow.status == "waiting")
            .where(PendingRow.kind == "question")
        )
    )
    return [PendingQuestion(agent_id=row.agent_id, asked_at=_aware(row.created_at)) for row in rows]


async def _recent(session: AsyncSession, agent_ids: list[str]) -> dict[str, list[str]]:
    recent: dict[str, list[str]] = {}
    for agent_id in agent_ids:
        rows = list(
            await session.scalars(
                select(Message)
                .where(Message.agent_id == agent_id)
                .where(Message.role == "user")
                .order_by(Message.created_at.desc())
                .limit(3)
            )
        )
        texts = [_part_text(row.parts) for row in reversed(rows)]
        recent[agent_id] = [text for text in texts if text != ""]
    return recent


async def _spawn(message: RoutedMessage, job_id: str) -> AgentRecord:
    title, summary = lane_text(message.text)
    return await AgentService().spawn(
        message.bot_id,
        origin_job_id=job_id,
        title=title,
        summary=summary,
    )


async def _attach_user_message(
    job_id: str,
    agent: AgentRecord,
    bot: BotRecord,
    text: str,
    decision: RouteDecision,
) -> str:
    now = utcnow()
    turn_id = new_id("turn_")
    message_id = new_id("msg_")
    async with open_session() as session:
        session.add(
            TurnRow(
                id=turn_id,
                agent_id=agent.id,
                thread_id=agent.thread_id,
                job_ids=[job_id],
                status="queued",
                model=bot.model,
                usage={},
                model_messages=None,
                started_at=now,
                finished_at=None,
            )
        )
        await session.flush()
        session.add(
            Message(
                id=message_id,
                thread_id=agent.thread_id,
                turn_id=turn_id,
                agent_id=agent.id,
                role="user",
                author="user",
                parts=_message_parts(text, decision, agent.title),
                created_at=now,
            )
        )
        session.add(RouteDecisionRow(id=new_id("rd_"), message_id=message_id, created_at=now))
        await session.commit()
    return message_id


async def _job_for_message(message_id: str) -> tuple[str, str, str | None, str]:
    async with open_session() as session:
        message = await session.get(Message, message_id)
        if message is None:
            raise DomainError("not_found", "message not found")
        turn = await session.get(TurnRow, message.turn_id)
        if turn is None or len(turn.job_ids) == 0:
            raise DomainError("not_found", "job not found")
        job = await session.get(JobRow, turn.job_ids[0])
        if job is None:
            raise DomainError("not_found", "job not found")
        return job.id, job.to_bot_id, job.route_decision_id, job.status


async def _running_turn(agent_id: str) -> str | None:
    async with open_session() as session:
        return await session.scalar(
            select(TurnRow.id)
            .where(TurnRow.agent_id == agent_id)
            .where(TurnRow.status.in_(("running", "waiting")))
            .limit(1)
        )


async def _ahead(bot_id: str, job_id: str) -> int:
    async with open_session() as session:
        rows = list(
            await session.scalars(
                select(JobRow.id)
                .where(JobRow.to_bot_id == bot_id)
                .where(JobRow.status.in_(("queued", "started")))
                .where(JobRow.id != job_id)
            )
        )
    return len(rows)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _message_parts(text: str, decision: RouteDecision, title: str) -> list[dict[str, str]]:
    """Text plus the chip the chat reads from ``part.type``."""
    parts: list[dict[str, str]] = [{"type": "text", "text": text}]
    if decision.ask_user:
        parts.append({"type": "routing_ask", "choices": "|".join(decision.choices)})
        return parts
    parts.append({"type": "routing", "intent": decision.intent, "title": title})
    return parts


def _part_text(parts: list[object]) -> str:
    chunks: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = cast("dict[object, object]", part).get("text")
        if isinstance(text, str):
            chunks.append(text)
    return "\n".join(chunks)
