"""Main dashboard read model (plan fleet-dashboards, phase 1).

Reads the host tables, not the event outbox: the outbox is pruned and only
signals that something changed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.config import Settings
from sevn.domain.session import open_session
from sevn.runtime.usage import cost_of, cost_source_of, tokens_of
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import Bot as BotRow
from sevn.store.models import Message, PendingRequest
from sevn.store.models import Turn as TurnRow

type FleetBotStatus = Literal["running", "waiting", "idle", "quiet"]

DAYS = 14
FINISHED_LIMIT = 20
PREVIEW_LIMIT = 160

_OPEN = ("running", "waiting", "idle")
_ENDED = ("done", "failed", "cancelled", "interrupted")


class FleetBot(BaseModel):
    """One bot on the dashboard header."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    title: str
    avatar: str
    paused: bool
    status: FleetBotStatus
    open_agents: int
    waiting: int


class FleetWaiting(BaseModel):
    """One request waiting on the owner."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    text: str
    name: str
    args: dict[str, object]
    bot_id: str
    bot_name: str
    agent_id: str
    agent_title: str
    turn_id: str
    created_at: datetime


class FleetFinished(BaseModel):
    """One turn that ended."""

    model_config = ConfigDict(extra="forbid")

    turn_id: str
    status: str
    preview: str
    bot_id: str
    bot_name: str
    agent_id: str
    agent_title: str
    finished_at: datetime


class FleetDay(BaseModel):
    """Turns one bot finished on one UTC day, and what the priced ones cost."""

    model_config = ConfigDict(extra="forbid")

    bot_id: str
    day: str
    turns: int
    cost_usd: float
    unpriced: int


class FleetKpi(BaseModel):
    """One tile on the KPI strip. ``value`` is null when it cannot be read."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    value: float | None
    unit: str
    source: str
    note: str
    limit: int | None = None
    unpriced: int | None = None
    subscription: int | None = None


class FleetOverview(BaseModel):
    """Everything the main dashboard shows, read at ``as_of``."""

    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    days: list[str]
    kpis: list[FleetKpi]
    bots: list[FleetBot]
    waiting: list[FleetWaiting]
    finished: list[FleetFinished]
    activity: list[FleetDay]


async def overview(*, bot_id: str | None = None) -> FleetOverview:
    """Read the dashboard. ``bot_id`` narrows only the finished list."""
    now = utcnow()
    days = _days(now.date())
    async with open_session() as session:
        bots = list(await session.scalars(select(BotRow).order_by(BotRow.created_at, BotRow.id)))
        names = {bot.id: bot.name for bot in bots}
        waiting = await _waiting(session, names)
        finished = await _finished(session, names, bot_id)
        activity = await _activity(session, days[0])
        statuses = await _agent_statuses(session)
        today = await _today(session, days[-1])
        running = await _running_turns(session)
    counts = Counter(item.bot_id for item in waiting)
    return FleetOverview(
        as_of=now,
        days=[day.isoformat() for day in days],
        kpis=_kpis(today, waiting=len(waiting), running=running),
        bots=[_bot(bot, statuses.get(bot.id, []), counts[bot.id]) for bot in bots],
        waiting=waiting,
        finished=finished,
        activity=activity,
    )


def _days(today: date) -> list[date]:
    return [today - timedelta(days=offset) for offset in range(DAYS - 1, -1, -1)]


def _bot(row: BotRow, statuses: list[str], waiting: int) -> FleetBot:
    return FleetBot(
        id=row.id,
        name=row.name,
        title=row.title,
        avatar=row.avatar,
        paused=row.paused,
        status=_bot_status(statuses, waiting),
        open_agents=sum(1 for status in statuses if status in _OPEN),
        waiting=waiting,
    )


def _bot_status(statuses: list[str], waiting: int) -> FleetBotStatus:
    if "running" in statuses:
        return "running"
    if waiting > 0 or "waiting" in statuses:
        return "waiting"
    if "idle" in statuses:
        return "idle"
    return "quiet"


async def _agent_statuses(session: AsyncSession) -> dict[str, list[str]]:
    rows = await session.execute(select(AgentRow.bot_id, AgentRow.status))
    found: dict[str, list[str]] = {}
    for bot_id, status in rows:
        found.setdefault(bot_id, []).append(status)
    return found


async def _waiting(session: AsyncSession, names: dict[str, str]) -> list[FleetWaiting]:
    rows = await session.execute(
        select(PendingRequest, AgentRow)
        .join(AgentRow, PendingRequest.agent_id == AgentRow.id)
        .where(PendingRequest.status == "waiting")
        .order_by(PendingRequest.created_at, PendingRequest.id)
    )
    items: list[FleetWaiting] = []
    for pending, agent in rows:
        name, args, text = _request_view(pending.kind, pending.payload)
        items.append(
            FleetWaiting(
                id=pending.id,
                kind=pending.kind,
                text=text,
                name=name,
                args=args,
                bot_id=agent.bot_id,
                bot_name=names.get(agent.bot_id, ""),
                agent_id=agent.id,
                agent_title=agent.title,
                turn_id=pending.turn_id,
                created_at=_utc(pending.created_at),
            )
        )
    return items


async def _finished(
    session: AsyncSession,
    names: dict[str, str],
    bot_id: str | None,
) -> list[FleetFinished]:
    stmt = (
        select(TurnRow, AgentRow)
        .join(AgentRow, TurnRow.agent_id == AgentRow.id)
        .where(TurnRow.status.in_(_ENDED))
        .where(TurnRow.finished_at.is_not(None))
    )
    if bot_id is not None:
        stmt = stmt.where(AgentRow.bot_id == bot_id)
    rows = list(
        (
            await session.execute(
                stmt.order_by(TurnRow.finished_at.desc(), TurnRow.id.desc()).limit(FINISHED_LIMIT)
            )
        ).all()
    )
    previews = await _previews(session, [turn.id for turn, _agent in rows])
    items: list[FleetFinished] = []
    for turn, agent in rows:
        finished_at = turn.finished_at if turn.finished_at is not None else turn.started_at
        items.append(
            FleetFinished(
                turn_id=turn.id,
                status=turn.status,
                preview=previews.get(turn.id, ""),
                bot_id=agent.bot_id,
                bot_name=names.get(agent.bot_id, ""),
                agent_id=agent.id,
                agent_title=agent.title,
                finished_at=_utc(finished_at),
            )
        )
    return items


async def _previews(session: AsyncSession, turn_ids: list[str]) -> dict[str, str]:
    """First line of each turn's latest assistant message."""
    if not turn_ids:
        return {}
    rows = await session.execute(
        select(Message.turn_id, Message.parts)
        .where(Message.turn_id.in_(turn_ids))
        .where(Message.role == "assistant")
        .order_by(Message.created_at, Message.id)
    )
    found: dict[str, str] = {}
    for turn_id, parts in rows:
        text = _first_line(_text(parts))
        if text != "":
            found[turn_id] = text
    return found


async def _activity(session: AsyncSession, first: date) -> list[FleetDay]:
    start = datetime(first.year, first.month, first.day, tzinfo=UTC)
    rows = await session.execute(
        select(AgentRow.bot_id, TurnRow.status, TurnRow.finished_at, TurnRow.usage)
        .join(AgentRow, TurnRow.agent_id == AgentRow.id)
        .where(TurnRow.status.in_(_ENDED))
        .where(TurnRow.finished_at.is_not(None))
        .where(TurnRow.finished_at >= start)
    )
    counts: Counter[tuple[str, str]] = Counter()
    costs: dict[tuple[str, str], float] = {}
    unpriced: Counter[tuple[str, str]] = Counter()
    for bot_id, status, finished_at, usage in rows:
        if finished_at is None:
            continue
        stamp = _utc(finished_at)
        if stamp < start:
            continue
        key = (bot_id, stamp.date().isoformat())
        if status == "done":
            counts[key] += 1
        spent = _spend(usage)
        if spent is _UNPRICED:
            unpriced[key] += 1
        elif isinstance(spent, float):
            costs[key] = costs.get(key, 0.0) + spent
    keys = sorted(set(counts) | set(costs) | set(unpriced))
    return [
        FleetDay(
            bot_id=bot_id,
            day=day,
            turns=counts[(bot_id, day)],
            cost_usd=round(costs.get((bot_id, day), 0.0), 6),
            unpriced=unpriced[(bot_id, day)],
        )
        for bot_id, day in keys
    ]


_UNPRICED = object()


def _spend(usage: object) -> float | object | None:
    """Dollars one turn cost, ``_UNPRICED``, or ``None`` when it has no dollar cost.

    Empty usage (a cancelled turn) is ``None``: nothing was recorded.
    A subscription turn is ``None``: it spends quota, not dollars.
    """
    body = _object_dict(usage)
    if not body:
        return None
    source = cost_source_of(body)
    if source == "subscription":
        return None
    if source == "unknown":
        return _UNPRICED
    return cost_of(body) or 0.0


@dataclass(slots=True)
class _Today:
    spend: float = 0.0
    tokens: int = 0
    unpriced: int = 0
    subscription: int = 0


async def _today(session: AsyncSession, today: date) -> _Today:
    start = datetime(today.year, today.month, today.day, tzinfo=UTC)
    rows = await session.execute(
        select(TurnRow.finished_at, TurnRow.usage)
        .where(TurnRow.status.in_(_ENDED))
        .where(TurnRow.finished_at.is_not(None))
        .where(TurnRow.finished_at >= start)
    )
    found = _Today()
    for finished_at, usage in rows:
        if finished_at is None or _utc(finished_at) < start:
            continue
        body = _object_dict(usage) or {}
        found.tokens += tokens_of(body)
        if body and cost_source_of(body) == "subscription":
            found.subscription += 1
        spent = _spend(body)
        if spent is _UNPRICED:
            found.unpriced += 1
        elif isinstance(spent, float):
            found.spend += spent
    return found


async def _running_turns(session: AsyncSession) -> int:
    value = await session.scalar(
        select(func.count()).select_from(TurnRow).where(TurnRow.status == "running")
    )
    return int(value or 0)


def _kpis(today: _Today, *, waiting: int, running: int) -> list[FleetKpi]:
    notes = ["turns finished since 00:00 UTC", "routing calls not included"]
    if today.unpriced:
        notes.append(f"{today.unpriced} unpriced")
    if today.subscription:
        notes.append(f"{today.subscription} on subscription")
    return [
        FleetKpi(
            key="spend_today",
            label="Spend today",
            value=round(today.spend, 6),
            unit="USD",
            source="turn usage priced with genai-prices",
            note="; ".join(notes),
            unpriced=today.unpriced,
            subscription=today.subscription,
        ),
        FleetKpi(
            key="tokens_today",
            label="Tokens today",
            value=float(today.tokens),
            unit="tokens",
            source="turn usage (input + output)",
            note="turns finished since 00:00 UTC",
        ),
        FleetKpi(
            key="waiting",
            label="Waiting on you",
            value=float(waiting),
            unit="",
            source="pending requests",
            note="approvals and questions",
        ),
        FleetKpi(
            key="running",
            label="Running turns",
            value=float(running),
            unit="",
            source="turns",
            note=f"host limit {_running_limit()}",
            limit=_running_limit(),
        ),
    ]


def _running_limit() -> int:
    return Settings.load().runtime.max_running_turns


def _request_view(kind: str, payload: object) -> tuple[str, dict[str, object], str]:
    """Tool name, arguments, and the line a card shows."""
    body = _object_dict(payload) or {}
    raw_name = body.get("name")
    name = raw_name if isinstance(raw_name, str) else ""
    args = _object_dict(body.get("args")) or {}
    raw_text = body.get("text")
    if kind == "question" and isinstance(raw_text, str) and raw_text != "":
        return name, args, raw_text
    question = args.get("question")
    if kind == "question" and isinstance(question, str):
        return name, args, question
    return name, args, name


def _text(parts: object) -> str:
    if not isinstance(parts, list):
        return ""
    chunks: list[str] = []
    for part in cast("list[object]", parts):
        body = _object_dict(part)
        if body is None or body.get("type") != "text":
            continue
        text = body.get("text")
        if isinstance(text, str):
            chunks.append(text)
    return "".join(chunks)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned != "":
            return cleaned[:PREVIEW_LIMIT].rstrip()
    return ""


def _object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    mapped: dict[str, object] = {}
    for key, item in cast("dict[object, object]", value).items():
        if isinstance(key, str):
            mapped[key] = item
    return mapped


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
