"""The Upcoming panel: routines, what their runs cost, and a 7-day projection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.domain.cron import parse, runs_between
from sevn.domain.spend import ENDED, priced_cost
from sevn.runtime.usage import cost_source_of
from sevn.store.models import Job as JobRow
from sevn.store.models import Routine
from sevn.store.models import Turn as TurnRow

type Outcome = Literal["ok", "noop", "failed", "cancelled", "running"]

WINDOW = timedelta(days=30)
NOTHING_USEFUL = timedelta(days=14)
PROJECTION = timedelta(days=7)
_RUN_LIMIT = 7 * 24 * 60


class FleetRoutine(BaseModel):
    """One routine on the Upcoming panel. Counts and costs cover 30 days."""

    model_config = ConfigDict(extra="forbid")

    id: str
    bot_id: str
    bot_name: str
    name: str
    schedule: str
    timezone: str
    status: str
    paused_reason: str | None
    next_run: datetime | None
    last_run: datetime | None
    last_outcome: Outcome | None
    last_useful_at: datetime | None
    runs_30d: int
    cost_30d_usd: float
    cost_per_run_usd: float | None
    unpriced_runs_30d: int
    runs_next_7d: int
    candidate_to_cancel: bool


@dataclass(slots=True)
class _Runs:
    count: int = 0
    priced: int = 0
    cost: float = 0.0
    unpriced: int = 0
    useful: datetime | None = None
    latest: tuple[datetime, Outcome] | None = None
    jobs: list[str] = field(default_factory=list[str])


async def upcoming(
    session: AsyncSession,
    names: dict[str, str],
    now: datetime,
) -> tuple[list[FleetRoutine], float, int]:
    """Routines that are not cancelled, the projected 7-day cost, and how many
    routines with runs in the next 7 days have no known cost per run."""
    routines = list(await session.scalars(select(Routine).where(Routine.status != "cancelled")))
    if not routines:
        return [], 0.0, 0
    runs = await _runs(session, [row.id for row in routines], now)
    items: list[FleetRoutine] = []
    projection = 0.0
    unpriced = 0
    for row in routines:
        stats = runs.get(row.id, _Runs())
        per_run = round(stats.cost / stats.priced, 6) if stats.priced else None
        ahead = _runs_ahead(row, now)
        if per_run is not None:
            projection += per_run * ahead
        elif ahead > 0:
            unpriced += 1
        items.append(
            FleetRoutine(
                id=row.id,
                bot_id=row.bot_id,
                bot_name=names.get(row.bot_id, ""),
                name=row.name,
                schedule=row.schedule,
                timezone=row.timezone,
                status=row.status,
                paused_reason=row.paused_reason,
                next_run=row.next_run,
                last_run=row.last_run,
                last_outcome=None if stats.latest is None else stats.latest[1],
                last_useful_at=stats.useful,
                runs_30d=stats.count,
                cost_30d_usd=round(stats.cost, 6),
                cost_per_run_usd=per_run,
                unpriced_runs_30d=stats.unpriced,
                runs_next_7d=ahead,
                candidate_to_cancel=_candidate(row, stats, now),
            )
        )
    items.sort(key=_order)
    return items, round(projection, 6), unpriced


async def _runs(session: AsyncSession, ids: list[str], now: datetime) -> dict[str, _Runs]:
    since = now - WINDOW
    jobs = list(
        await session.scalars(
            select(JobRow).where(JobRow.routine_id.in_(ids)).where(JobRow.created_at >= since)
        )
    )
    found: dict[str, _Runs] = {}
    owner: dict[str, str] = {}
    for job in jobs:
        if job.routine_id is None:
            continue
        stats = found.setdefault(job.routine_id, _Runs())
        owner[job.id] = job.routine_id
        outcome = _outcome(job)
        created = _utc(job.created_at)
        if stats.latest is None or created > stats.latest[0]:
            stats.latest = (created, outcome)
        if job.status not in ("done", "failed"):
            continue
        stats.count += 1
        if job.status == "done" and not job.silent and job.finished_at is not None:
            finished = _utc(job.finished_at)
            if stats.useful is None or finished > stats.useful:
                stats.useful = finished
    turns = await session.execute(
        select(TurnRow.job_ids, TurnRow.usage)
        .where(TurnRow.status.in_(ENDED))
        .where(TurnRow.finished_at.is_not(None))
        .where(TurnRow.finished_at >= since)
    )
    for job_ids, usage in turns:
        routine_id = next((owner[job] for job in job_ids if job in owner), None)
        if routine_id is None or not usage:
            continue
        stats = found[routine_id]
        cost = priced_cost(usage)
        if cost is not None:
            stats.priced += 1
            stats.cost += cost
        elif cost_source_of(usage) == "unknown":
            stats.unpriced += 1
    return found


def _outcome(job: JobRow) -> Outcome:
    if job.status == "done":
        return "noop" if job.silent else "ok"
    if job.status == "failed":
        return "failed"
    if job.status == "cancelled":
        return "cancelled"
    return "running"


def _runs_ahead(row: Routine, now: datetime) -> int:
    if row.status != "active":
        return 0
    try:
        spec = parse(row.schedule)
        zone = ZoneInfo(row.timezone)
    except (ValueError, ZoneInfoNotFoundError):
        return 0
    return runs_between(spec, now, now + PROJECTION, zone, limit=_RUN_LIMIT)


def _candidate(row: Routine, stats: _Runs, now: datetime) -> bool:
    """No useful run in 14 days, for a routine at least 14 days old."""
    if _utc(row.created_at) > now - NOTHING_USEFUL:
        return False
    return stats.useful is None or stats.useful < now - NOTHING_USEFUL


def _order(item: FleetRoutine) -> tuple[int, datetime, str, str]:
    """Active by next run, then paused by name."""
    if item.status == "active" and item.next_run is not None:
        return (0, item.next_run, "", item.id)
    return (1, datetime.max.replace(tzinfo=UTC), item.name.lower(), item.id)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
