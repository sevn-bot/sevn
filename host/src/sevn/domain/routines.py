"""Routines: a prompt a bot runs on a cron schedule (plan fleet-dashboards, phase 4).

Each run starts a fresh lane titled after the routine. A routine that missed
runs while the host was down runs once, then waits for its next slot. Daily
budgets pause routines with ``paused_reason="budget"``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.config import Settings
from sevn.domain.agents import AgentService
from sevn.domain.bots import BotService
from sevn.domain.cron import CronSpec, next_after, parse
from sevn.domain.errors import DomainError
from sevn.domain.ids import new_id, stable_id
from sevn.domain.session import open_session
from sevn.domain.spend import day_start, spend_by_bot
from sevn.log import logger
from sevn.protocol.hub import Hub
from sevn.store.db import utcnow
from sevn.store.models import Bot as BotRow
from sevn.store.models import Job as JobRow
from sevn.store.models import Routine
from sevn.tools.routine import SILENT_MARKER

type RoutineStatus = Literal["active", "paused", "cancelled"]

_NAME_LIMIT = 80
_SUMMARY_LIMIT = 200
_SILENT_HINT = (
    "\n\n(Scheduled run of the routine “{name}”. If nothing here needs the "
    "owner, call routine.silent.)"
)
# Claude bots get no sevn tools, so they say it in the reply instead.
_SILENT_REPLY_HINT = (
    "\n\n(Scheduled run of the routine “{name}”. If nothing here needs the "
    "owner, start your reply with {marker}.)"
)


def _silent_hint(runtime: str, name: str) -> str:
    if runtime == "claude":
        return _SILENT_REPLY_HINT.format(name=name, marker=SILENT_MARKER)
    return _SILENT_HINT.format(name=name)


class RoutineRecord(BaseModel):
    """One routine as the protocol returns it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    bot_id: str
    name: str
    schedule: str
    timezone: str
    text: str
    status: RoutineStatus
    paused_reason: str | None
    next_run: datetime | None
    last_run: datetime | None
    created_at: datetime
    updated_at: datetime


class RoutineService:
    """Create, change, pause, resume and cancel routines."""

    async def create(
        self,
        bot_id: str,
        *,
        name: str,
        schedule: str,
        timezone: str,
        text: str,
    ) -> RoutineRecord:
        cleaned_name = _name(name)
        cleaned_text = _text(text)
        zone = _zone(timezone)
        spec = _spec(schedule)
        now = utcnow()
        async with open_session() as session:
            if await session.get(BotRow, bot_id) is None:
                raise DomainError("not_found", "bot not found")
            row = Routine(
                id=new_id("rtn_"),
                bot_id=bot_id,
                name=cleaned_name,
                schedule=schedule.strip(),
                timezone=timezone,
                text=cleaned_text,
                status="active",
                paused_reason=None,
                next_run=next_after(spec, now, zone),
                last_run=None,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.commit()
            return _record(row)

    async def list(
        self, bot_id: str | None = None, *, include_cancelled: bool = False
    ) -> list[RoutineRecord]:
        async with open_session() as session:
            stmt = select(Routine).order_by(Routine.created_at, Routine.id)
            if bot_id is not None:
                stmt = stmt.where(Routine.bot_id == bot_id)
            if not include_cancelled:
                stmt = stmt.where(Routine.status != "cancelled")
            return [_record(row) for row in await session.scalars(stmt)]

    async def update(
        self,
        routine_id: str,
        *,
        name: str | None = None,
        schedule: str | None = None,
        timezone: str | None = None,
        text: str | None = None,
    ) -> RoutineRecord:
        async with open_session() as session:
            row = await _open(session, routine_id)
            if name is not None:
                row.name = _name(name)
            if text is not None:
                row.text = _text(text)
            if schedule is not None:
                _spec(schedule)
                row.schedule = schedule.strip()
            if timezone is not None:
                _zone(timezone)
                row.timezone = timezone
            now = utcnow()
            if row.status == "active" and (schedule is not None or timezone is not None):
                row.next_run = next_after(_spec(row.schedule), now, _zone(row.timezone))
            row.updated_at = now
            await session.commit()
            return _record(row)

    async def pause(self, routine_id: str, *, reason: str = "user") -> RoutineRecord:
        async with open_session() as session:
            row = await _open(session, routine_id)
            row.status = "paused"
            row.paused_reason = reason
            row.next_run = None
            row.updated_at = utcnow()
            await session.commit()
            return _record(row)

    async def resume(self, routine_id: str) -> RoutineRecord:
        """Start again from the next slot. Slots missed while paused do not run."""
        async with open_session() as session:
            row = await _open(session, routine_id)
            now = utcnow()
            row.status = "active"
            row.paused_reason = None
            row.next_run = next_after(_spec(row.schedule), now, _zone(row.timezone))
            row.updated_at = now
            await session.commit()
            return _record(row)

    async def cancel(self, routine_id: str) -> RoutineRecord:
        async with open_session() as session:
            row = await _open(session, routine_id)
            row.status = "cancelled"
            row.paused_reason = None
            row.next_run = None
            row.updated_at = utcnow()
            await session.commit()
            return _record(row)


async def run_due(hub: Hub, *, now: datetime | None = None) -> list[str]:
    """Pause routines over budget, then run every due routine once.

    Returns the ids of the jobs queued. A routine whose bot is paused skips
    this slot. The next run is always the first slot after ``now``, so a long
    outage gives one catch-up run, not one per missed slot.
    """
    moment = now if now is not None else utcnow()
    await _apply_budgets(hub, moment)
    async with open_session() as session:
        due = list(
            await session.scalars(
                select(Routine)
                .where(Routine.status == "active")
                .where(Routine.next_run.is_not(None))
                .where(Routine.next_run <= moment)
                .order_by(Routine.next_run, Routine.id)
            )
        )
    jobs: list[str] = []
    for routine in due:
        try:
            job_id = await _run(hub, routine, moment)
        except Exception:  # noqa: BLE001 — one broken routine must not stop the others
            logger.exception("routine run failed")
            continue
        if job_id is not None:
            jobs.append(job_id)
    return jobs


async def _run(hub: Hub, routine: Routine, now: datetime) -> str | None:
    """Run one due occurrence at most once.

    The job id comes from the routine and its slot, so a sweep that stopped
    after queueing the job but before moving the cursor finds that job on
    the next try and only moves the cursor. ``routine.run`` is announced
    after the cursor moves; losing it loses a live event, never a run.
    """
    from sevn.domain.routing import queue_on_lane

    slot = routine.next_run
    if slot is None:
        return None
    following = next_after(_spec(routine.schedule), now, _zone(routine.timezone))
    job_id = occurrence_job_id(routine.id, slot)
    bot = await BotService().get(routine.bot_id)
    queued: str | None = None
    agent_id: str | None = None
    if not bot.paused and not await _job_exists(job_id):
        agent = await AgentService().spawn(
            bot.id,
            title=routine.name,
            summary=routine.text[:_SUMMARY_LIMIT],
        )
        try:
            queued = await queue_on_lane(
                bot,
                agent,
                routine.text + _silent_hint(bot.runtime, routine.name),
                origin="routine",
                intent="new_request",
                path="routine",
                hub=hub,
                routine_id=routine.id,
                job_id=job_id,
            )
        except IntegrityError:
            # Another sweep queued this occurrence first.
            queued = None
        agent_id = agent.id
    async with open_session() as session:
        values: dict[str, object] = {"next_run": following, "updated_at": utcnow()}
        if queued is not None:
            values["last_run"] = now
        await session.execute(
            update(Routine)
            .where(Routine.id == routine.id)
            .where(Routine.next_run == slot)
            .values(**values)
        )
        await session.commit()
    if queued is not None:
        await hub.emit(
            "routine.run",
            routine.id,
            {
                "routine_id": routine.id,
                "job_id": queued,
                "agent_id": agent_id,
                "bot_id": bot.id,
            },
        )
    return queued


def occurrence_job_id(routine_id: str, slot: datetime) -> str:
    """The one job id for a routine's run at ``slot``."""
    return stable_id("job_", routine_id, _utc(slot).isoformat())


async def _job_exists(job_id: str) -> bool:
    async with open_session() as session:
        return await session.get(JobRow, job_id) is not None


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


async def _apply_budgets(hub: Hub, now: datetime) -> None:
    budgets = Settings.load().budgets
    if budgets.daily_usd_per_bot is None and budgets.daily_usd_host is None:
        return
    async with open_session() as session:
        spent = await spend_by_bot(session, day_start(now))
        host_over = (
            budgets.daily_usd_host is not None and sum(spent.values()) >= budgets.daily_usd_host
        )
        per_bot = budgets.daily_usd_per_bot
        over = {bot for bot, value in spent.items() if per_bot is not None and value >= per_bot}
        rows = list(await session.scalars(select(Routine).where(Routine.status == "active")))
        paused: list[Routine] = []
        for row in rows:
            if host_over or row.bot_id in over:
                row.status = "paused"
                row.paused_reason = "budget"
                row.next_run = None
                row.updated_at = utcnow()
                paused.append(row)
        await session.commit()
    for row in paused:
        logger.info("routine paused by budget")
        await hub.emit("routine.updated", row.id, routine_event(_record(row)))


def routine_event(record: RoutineRecord) -> dict[str, object]:
    return {
        "routine_id": record.id,
        "bot_id": record.bot_id,
        "status": record.status,
        "paused_reason": record.paused_reason,
    }


async def _open(session: AsyncSession, routine_id: str) -> Routine:
    row = await session.get(Routine, routine_id)
    if row is None:
        raise DomainError("not_found", "routine not found")
    if row.status == "cancelled":
        raise DomainError("invalid_params", "routine is cancelled")
    return row


def _spec(schedule: str) -> CronSpec:
    try:
        return parse(schedule)
    except ValueError as exc:
        raise DomainError("invalid_params", f"schedule: {exc}") from None


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise DomainError("invalid_params", "unknown timezone") from None


def _name(raw: str) -> str:
    cleaned = " ".join(raw.split())
    if cleaned == "":
        raise DomainError("invalid_params", "name is empty")
    return cleaned[:_NAME_LIMIT]


def _text(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned == "":
        raise DomainError("invalid_params", "text is empty")
    return cleaned


def _record(row: Routine) -> RoutineRecord:
    status: RoutineStatus = "active"
    if row.status == "paused":
        status = "paused"
    elif row.status == "cancelled":
        status = "cancelled"
    return RoutineRecord(
        id=row.id,
        bot_id=row.bot_id,
        name=row.name,
        schedule=row.schedule,
        timezone=row.timezone,
        text=row.text,
        status=status,
        paused_reason=row.paused_reason,
        next_run=row.next_run,
        last_run=row.last_run,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
