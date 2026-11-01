"""Bot-reported metrics (plan fleet-dashboards, phase 6).

Every value carries a source and the time it was true (``as_of``). A value
older than its freshness budget is shown as stale, a failed read as
unavailable, and two bots disagreeing as a conflict. Nothing is smoothed or
filled in.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.domain.errors import DomainError
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.store.db import utcnow
from sevn.store.models import MetricPoint

type MetricStatus = Literal["ok", "stale", "error", "conflict"]

MAX_TILES = 8
_KEY = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
_MAX_FRESHNESS = 60 * 24 * 30
_CLOCK_SKEW = timedelta(minutes=5)
_DAY = timedelta(hours=24)
_DELTA_SPAN = timedelta(hours=48)
_TEXT_LIMIT = 120


class MetricReport(BaseModel):
    """One bot's latest value for a key."""

    model_config = ConfigDict(extra="forbid")

    bot_id: str
    bot_name: str
    value: float | None
    as_of: datetime
    source: str


class FleetMetric(BaseModel):
    """One metric tile: the newest report, plus every bot's when they disagree."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    value: float | None
    unit: str
    source: str
    as_of: datetime
    bot_id: str
    bot_name: str
    status: MetricStatus
    delta_24h: float | None
    freshness_minutes: int
    shareable: bool
    reports: list[MetricReport]


async def report(
    bot_id: str,
    *,
    key: str,
    value: float | None,
    source: str,
    unit: str = "",
    label: str = "",
    as_of: str | None = None,
    freshness_minutes: int = 1440,
    shareable: bool = True,
) -> str:
    """Store one value. ``value`` null records that the read failed."""
    if _KEY.fullmatch(key) is None:
        raise DomainError("invalid_params", "key must be lowercase letters, digits, . _ or -")
    cleaned_source = " ".join(source.split())
    if cleaned_source == "":
        raise DomainError("invalid_params", "source is required: say where the value came from")
    if value is not None and not math.isfinite(value):
        # Infinity or NaN cannot travel in a JSON frame.
        raise DomainError("invalid_params", "value must be a finite number")
    if not 1 <= freshness_minutes <= _MAX_FRESHNESS:
        raise DomainError("invalid_params", "freshness_minutes must be 1 to 43200")
    now = utcnow()
    moment = _moment(as_of, now)
    point_id = new_id("met_")
    async with open_session() as session:
        session.add(
            MetricPoint(
                id=point_id,
                bot_id=bot_id,
                key=key,
                label=" ".join(label.split())[:_TEXT_LIMIT] or key,
                value=value,
                unit=unit.strip()[:_TEXT_LIMIT],
                source=cleaned_source[:_TEXT_LIMIT],
                status="ok" if value is not None else "error",
                as_of=moment,
                freshness_minutes=freshness_minutes,
                shareable=shareable,
                created_at=now,
            )
        )
        await session.commit()
    return point_id


def _moment(raw: str | None, now: datetime) -> datetime:
    if raw is None or raw == "":
        return now
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise DomainError("invalid_params", "as_of must be ISO 8601") from None
    if parsed.tzinfo is None:
        raise DomainError("invalid_params", "as_of needs a timezone offset")
    if parsed > now + _CLOCK_SKEW:
        raise DomainError("invalid_params", "as_of is in the future")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class _Point:
    bot_id: str
    key: str
    label: str
    value: float | None
    unit: str
    source: str
    status: str
    as_of: datetime
    freshness_minutes: int
    shareable: bool


async def tiles(
    session: AsyncSession,
    names: dict[str, str],
    now: datetime,
    *,
    limit: int | None = MAX_TILES,
) -> list[FleetMetric]:
    """The newest ``limit`` metrics, one tile per key. ``None`` returns every key.

    Reads only each bot's latest point per key, then one indexed lookup per
    tile for its 24-hour change, so a long history does not slow the read.
    """
    newest_at = (
        select(
            MetricPoint.key,
            MetricPoint.bot_id,
            func.max(MetricPoint.as_of).label("as_of"),
        )
        .group_by(MetricPoint.key, MetricPoint.bot_id)
        .subquery()
    )
    rows = await session.scalars(
        select(MetricPoint)
        .join(
            newest_at,
            and_(
                MetricPoint.key == newest_at.c.key,
                MetricPoint.bot_id == newest_at.c.bot_id,
                MetricPoint.as_of == newest_at.c.as_of,
            ),
        )
        .order_by(MetricPoint.created_at)
    )
    latest: dict[tuple[str, str], _Point] = {}
    for row in rows:
        # Two points with the same time: the later write wins.
        latest[(row.key, row.bot_id)] = _point(row)
    by_key: dict[str, list[_Point]] = {}
    for (key, _bot), point in latest.items():
        by_key.setdefault(key, []).append(point)
    ordered = sorted(
        by_key.values(),
        key=lambda points: (max(point.as_of for point in points), points[0].key),
        reverse=True,
    )
    chosen = ordered if limit is None else ordered[:limit]
    found: list[FleetMetric] = []
    for points in chosen:
        points.sort(key=lambda item: item.as_of, reverse=True)
        found.append(_tile(points, names, now, await _delta(session, points[0])))
    return found


async def all_tiles(now: datetime) -> list[FleetMetric]:
    """Every metric key's tile. The brief checks them all, not only the 8 shown."""
    from sevn.store.models import Bot as BotRow

    async with open_session() as session:
        names = {bot.id: bot.name for bot in await session.scalars(select(BotRow))}
        return await tiles(session, names, now, limit=None)


def _point(row: MetricPoint) -> _Point:
    return _Point(
        bot_id=row.bot_id,
        key=row.key,
        label=row.label,
        value=row.value,
        unit=row.unit,
        source=row.source,
        status=row.status,
        as_of=_utc(row.as_of),
        freshness_minutes=row.freshness_minutes,
        shareable=row.shareable,
    )


def _tile(
    entries: list[_Point],
    names: dict[str, str],
    now: datetime,
    delta: float | None,
) -> FleetMetric:
    """``entries`` holds each bot's latest point for one key, newest first."""
    newest = entries[0]
    status: MetricStatus = "ok"
    if newest.status == "error" or newest.value is None:
        status = "error"
    elif _stale(newest, now):
        status = "stale"
    current = {
        point.value
        for point in entries
        if point.value is not None and point.status == "ok" and not _stale(point, now)
    }
    if status == "ok" and len(current) > 1:
        status = "conflict"
    return FleetMetric(
        key=newest.key,
        label=newest.label,
        value=newest.value,
        unit=newest.unit,
        source=newest.source,
        as_of=newest.as_of,
        bot_id=newest.bot_id,
        bot_name=names.get(newest.bot_id, ""),
        status=status,
        delta_24h=delta,
        freshness_minutes=newest.freshness_minutes,
        shareable=all(point.shareable for point in entries),
        reports=[
            MetricReport(
                bot_id=point.bot_id,
                bot_name=names.get(point.bot_id, ""),
                value=point.value,
                as_of=point.as_of,
                source=point.source,
            )
            for point in entries
        ],
    )


def _stale(point: _Point, now: datetime) -> bool:
    return now - point.as_of > timedelta(minutes=point.freshness_minutes)


async def _delta(session: AsyncSession, newest: _Point) -> float | None:
    """Change since the last value from 24 to 48 hours before the newest."""
    if newest.value is None:
        return None
    earlier = await session.scalar(
        select(MetricPoint.value)
        .where(MetricPoint.key == newest.key)
        .where(MetricPoint.bot_id == newest.bot_id)
        .where(MetricPoint.value.is_not(None))
        .where(MetricPoint.as_of >= newest.as_of - _DELTA_SPAN)
        .where(MetricPoint.as_of <= newest.as_of - _DAY)
        .order_by(MetricPoint.as_of.desc())
        .limit(1)
    )
    if earlier is None:
        return None
    return round(newest.value - earlier, 6)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
