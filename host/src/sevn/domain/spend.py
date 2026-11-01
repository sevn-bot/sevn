"""Dollar spend from turn usage, shared by the dashboard and the budgets."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.runtime.usage import cost_of, cost_source_of
from sevn.store.models import Agent as AgentRow
from sevn.store.models import Turn as TurnRow

ENDED = ("done", "failed", "cancelled", "interrupted")


def priced_cost(usage: object) -> float | None:
    """Dollars a turn cost when its usage is priced (``price_table`` or ``local``)."""
    body = _mapping(usage)
    if not body:
        return None
    if cost_source_of(body) not in ("price_table", "local"):
        return None
    return cost_of(body) or 0.0


async def spend_by_bot(session: AsyncSession, since: datetime) -> dict[str, float]:
    """Priced spend per bot of turns that ended at or after ``since``."""
    rows = await session.execute(
        select(AgentRow.bot_id, TurnRow.finished_at, TurnRow.usage)
        .join(AgentRow, TurnRow.agent_id == AgentRow.id)
        .where(TurnRow.status.in_(ENDED))
        .where(TurnRow.finished_at.is_not(None))
        .where(TurnRow.finished_at >= since)
    )
    totals: dict[str, float] = {}
    for bot_id, finished_at, usage in rows:
        if finished_at is None or _utc(finished_at) < since:
            continue
        cost = priced_cost(usage)
        if cost is not None:
            totals[bot_id] = totals.get(bot_id, 0.0) + cost
    return totals


def day_start(now: datetime) -> datetime:
    """00:00 UTC of ``now``'s day."""
    moment = now.astimezone(UTC)
    return datetime(moment.year, moment.month, moment.day, tzinfo=UTC)


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    raw = cast("Mapping[object, object]", value)
    return {key: item for key, item in raw.items() if isinstance(key, str)}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
