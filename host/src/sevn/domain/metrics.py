"""Bot-reported metrics (plan fleet-dashboards, phase 6).

Every value carries a source and the time it was true (``as_of``). A value
older than its freshness budget is shown as stale, a failed read as
unavailable, and two bots disagreeing as a conflict. Nothing is smoothed or
filled in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
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
    limit: int = MAX_TILES,
) -> list[FleetMetric]:
    """The newest ``limit`` metrics, one tile per key."""
    rows = list(await session.scalars(select(MetricPoint).order_by(MetricPoint.as_of)))
    history: dict[tuple[str, str], list[_Point]] = {}
    for row in rows:
        point = _Point(
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
        history.setdefault((row.key, row.bot_id), []).append(point)
    latest: dict[str, list[tuple[_Point, list[_Point]]]] = {}
    for (key, _bot), points in history.items():
        points.sort(key=lambda item: item.as_of)
        latest.setdefault(key, []).append((points[-1], points))
    found = [_tile(entries, names, now) for entries in latest.values()]
    found.sort(key=lambda tile: (tile.as_of, tile.key), reverse=True)
    return found[:limit]


def _tile(
    entries: list[tuple[_Point, list[_Point]]],
    names: dict[str, str],
    now: datetime,
) -> FleetMetric:
    entries.sort(key=lambda item: item[0].as_of, reverse=True)
    newest, points = entries[0]
    status: MetricStatus = "ok"
    if newest.status == "error" or newest.value is None:
        status = "error"
    elif _stale(newest, now):
        status = "stale"
    current = {
        point.value
        for point, _ in entries
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
        delta_24h=_delta(newest, points),
        freshness_minutes=newest.freshness_minutes,
        shareable=all(point.shareable for point, _ in entries),
        reports=[
            MetricReport(
                bot_id=point.bot_id,
                bot_name=names.get(point.bot_id, ""),
                value=point.value,
                as_of=point.as_of,
                source=point.source,
            )
            for point, _ in entries
        ],
    )


def _stale(point: _Point, now: datetime) -> bool:
    return now - point.as_of > timedelta(minutes=point.freshness_minutes)


def _delta(newest: _Point, points: list[_Point]) -> float | None:
    """Change since the last value from 24 to 48 hours before the newest."""
    if newest.value is None:
        return None
    earlier = [
        point.value
        for point in points
        if point.value is not None
        and newest.as_of - _DELTA_SPAN <= point.as_of <= newest.as_of - _DAY
    ]
    if not earlier:
        return None
    return round(newest.value - earlier[-1], 6)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
