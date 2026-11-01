"""Read-only share links (plan fleet-dashboards, phase 6).

A link is ``/share/<id>/<secret>``. Only a SHA-256 of the secret is stored.
It expires, can be revoked, can be scoped to one bot, and counts its opens.

The snapshot behind a link is built for someone who is not the owner: counts,
statuses, schedules and shareable metrics. It never carries message text,
lane titles (they come from the owner's messages), question text, approval
arguments, routine prompts or metrics a bot marked not shareable.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from sevn.domain.errors import DomainError
from sevn.domain.fleet import FleetDay, FleetKpi, overview
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.log import logger
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import Bot as BotRow
from sevn.store.models import ShareLink
from sevn.store.models import Turn as TurnRow

type ShareStatus = Literal["active", "expired", "revoked"]

MAX_HOURS = 24 * 30
_LABEL_LIMIT = 80
_DAY = timedelta(hours=24)


class ShareRecord(BaseModel):
    """A share link as the owner sees it. The secret is shown once, at create."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    bot_id: str | None
    status: ShareStatus
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_opened_at: datetime | None
    opens: int


class SharedBot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    status: str


class SharedMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    value: float | None
    unit: str
    source: str
    as_of: datetime
    status: str
    delta_24h: float | None


class SharedRoutine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    bot_name: str
    schedule: str
    timezone: str
    status: str
    paused_reason: str | None
    next_run: datetime | None
    cost_per_run_usd: float | None
    runs_next_7d: int


class FinishedCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    done: int
    failed: int


class SharedFleet(BaseModel):
    """What a share link shows. Built when it is opened."""

    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    label: str
    scope_bot_name: str | None
    expires_at: datetime
    kpis: list[FleetKpi]
    bots: list[SharedBot]
    metrics: list[SharedMetric]
    days: list[str]
    activity: list[FleetDay]
    upcoming: list[SharedRoutine]
    projection_7d_usd: float | None
    waiting: int
    finished_24h: FinishedCounts


class ShareService:
    """Create, list and revoke share links. Owner only, through the protocol."""

    async def create(
        self, *, label: str, bot_id: str | None, expires_in_hours: int
    ) -> tuple[ShareRecord, str]:
        """Returns the record and the link path, the only time the secret is shown."""
        cleaned = " ".join(label.split())[:_LABEL_LIMIT]
        if cleaned == "":
            raise DomainError("invalid_params", "label is empty")
        if not 1 <= expires_in_hours <= MAX_HOURS:
            raise DomainError("invalid_params", f"expires_in_hours must be 1 to {MAX_HOURS}")
        secret = secrets.token_urlsafe(32)
        now = utcnow()
        async with open_session() as session:
            if bot_id is not None and await session.get(BotRow, bot_id) is None:
                raise DomainError("not_found", "bot not found")
            row = ShareLink(
                id=new_id("shr_"),
                secret_hash=_hash(secret),
                label=cleaned,
                bot_id=bot_id,
                created_at=now,
                expires_at=now + timedelta(hours=expires_in_hours),
                revoked_at=None,
                last_opened_at=None,
                opens=0,
            )
            session.add(row)
            await session.commit()
            return _record(row, now), f"/share/{row.id}/{secret}"

    async def list(self) -> list[ShareRecord]:
        now = utcnow()
        async with open_session() as session:
            rows = await session.scalars(
                select(ShareLink).order_by(ShareLink.created_at.desc(), ShareLink.id)
            )
            return [_record(row, now) for row in rows]

    async def revoke(self, share_id: str) -> ShareRecord:
        now = utcnow()
        async with open_session() as session:
            row = await session.get(ShareLink, share_id)
            if row is None:
                raise DomainError("not_found", "share link not found")
            if row.revoked_at is None:
                row.revoked_at = now
            await session.commit()
            return _record(row, now)


async def shared_snapshot(share_id: str, secret: str) -> SharedFleet:
    """The snapshot for a valid link. Every failure is the same ``not_found``."""
    now = utcnow()
    async with open_session() as session:
        row = await session.get(ShareLink, share_id)
        if (
            row is None
            or not hmac.compare_digest(row.secret_hash, _hash(secret))
            or row.revoked_at is not None
            or row.expires_at <= now
        ):
            raise DomainError("not_found", "share link not found")
        row.opens += 1
        row.last_opened_at = now
        label = row.label
        scope = row.bot_id
        expires_at = row.expires_at
        await session.commit()
    logger.info("share link opened")
    return await _snapshot(label=label, scope=scope, expires_at=expires_at)


async def _snapshot(*, label: str, scope: str | None, expires_at: datetime) -> SharedFleet:
    board = await overview()
    names = {bot.id: bot.name for bot in board.bots}

    def visible(bot_id: str) -> bool:
        return scope is None or bot_id == scope

    metrics = [
        SharedMetric(
            key=tile.key,
            label=tile.label,
            value=tile.value,
            unit=tile.unit,
            source=tile.source,
            as_of=tile.as_of,
            status=tile.status,
            delta_24h=tile.delta_24h,
        )
        for tile in board.metrics
        if tile.shareable and all(visible(report.bot_id) for report in tile.reports)
    ]
    done, failed = await _finished(board.as_of - _DAY, scope)
    return SharedFleet(
        as_of=board.as_of,
        label=label,
        scope_bot_name=None if scope is None else names.get(scope, ""),
        expires_at=expires_at,
        # Spend, tokens and running turns are host-wide; a bot-scoped link omits them.
        kpis=board.kpis if scope is None else [],
        bots=[
            SharedBot(id=bot.id, name=bot.name, status=bot.status)
            for bot in board.bots
            if visible(bot.id)
        ],
        metrics=metrics,
        days=board.days,
        activity=[row for row in board.activity if visible(row.bot_id)],
        upcoming=[
            SharedRoutine(
                name=item.name,
                bot_name=item.bot_name,
                schedule=item.schedule,
                timezone=item.timezone,
                status=item.status,
                paused_reason=item.paused_reason,
                next_run=item.next_run,
                cost_per_run_usd=item.cost_per_run_usd,
                runs_next_7d=item.runs_next_7d,
            )
            for item in board.upcoming
            if visible(item.bot_id)
        ],
        projection_7d_usd=board.projection_7d_usd if scope is None else None,
        waiting=sum(1 for item in board.waiting if visible(item.bot_id)),
        finished_24h=FinishedCounts(done=done, failed=failed),
    )


async def _finished(since: datetime, scope: str | None) -> tuple[int, int]:
    async with open_session() as session:
        stmt = (
            select(TurnRow.status)
            .join(AgentRow, TurnRow.agent_id == AgentRow.id)
            .where(TurnRow.status.in_(("done", "failed")))
            .where(TurnRow.finished_at.is_not(None))
            .where(TurnRow.finished_at >= since)
        )
        if scope is not None:
            stmt = stmt.where(AgentRow.bot_id == scope)
        statuses = list(await session.scalars(stmt))
    return statuses.count("done"), statuses.count("failed")


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _record(row: ShareLink, now: datetime) -> ShareRecord:
    status: ShareStatus = "active"
    if row.revoked_at is not None:
        status = "revoked"
    elif row.expires_at <= now:
        status = "expired"
    return ShareRecord(
        id=row.id,
        label=row.label,
        bot_id=row.bot_id,
        status=status,
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        last_opened_at=row.last_opened_at,
        opens=row.opens,
    )
