"""The 60-second daily brief (plan fleet-dashboards, phase 6).

Built when it is read, from the same data as the dashboard, and stamped with
the time it was built.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from sevn.domain.cron import parse, runs_between
from sevn.domain.fleet import (
    FleetFinished,
    FleetKpi,
    FleetOverview,
    FleetWaiting,
    finished_since,
    overview,
)
from sevn.domain.fleet_routines import FleetRoutine
from sevn.domain.metrics import FleetMetric, all_tiles
from sevn.domain.session import open_session
from sevn.store.models import Agent as AgentRow
from sevn.store.models import Bot as BotRow
from sevn.store.models import Routine
from sevn.store.models import Turn as TurnRow

type IssueKind = Literal[
    "failed_turns",
    "failed_routine",
    "overdue_question",
    "paused_by_budget",
    "stale_metric",
    "error_metric",
    "conflict_metric",
    "ollama_down",
]

_DAY = timedelta(hours=24)
_TOP = 3


class BriefRoutine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    bot_name: str
    next_run: datetime | None
    runs: int
    cost_per_run_usd: float | None


class BriefIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: IssueKind
    text: str


class FleetBrief(BaseModel):
    """What needs the owner, what finished, what runs today, and what broke."""

    model_config = ConfigDict(extra="forbid")

    built_at: datetime
    since: datetime
    kpis: list[FleetKpi]
    metric_changes: list[FleetMetric]
    decisions: list[FleetWaiting]
    decisions_total: int
    finished_done: int
    finished_failed: int
    finished_top: list[FleetFinished]
    routines_today: list[BriefRoutine]
    routines_today_usd: float
    routines_today_unpriced: int
    broken: list[BriefIssue]


async def brief() -> FleetBrief:
    board = await overview()
    now = board.as_of
    since = now - _DAY
    done, failed, failed_bots = await _ended(since)
    routines, today_usd, today_unpriced = await _today(board.upcoming, now)
    # The dashboard caps its metric strip and finished list; the brief does not.
    metrics = await all_tiles(now)
    return FleetBrief(
        built_at=now,
        since=since,
        kpis=board.kpis,
        metric_changes=[
            metric
            for metric in metrics
            if metric.delta_24h not in (None, 0) or metric.status != "ok"
        ],
        decisions=board.waiting[:_TOP],
        decisions_total=len(board.waiting),
        finished_done=done,
        finished_failed=failed,
        finished_top=await finished_since(since, status="done", limit=_TOP),
        routines_today=routines,
        routines_today_usd=round(today_usd, 6),
        routines_today_unpriced=today_unpriced,
        broken=_issues(board, metrics, now, failed, failed_bots),
    )


async def _ended(since: datetime) -> tuple[int, int, list[str]]:
    async with open_session() as session:
        rows = await session.execute(
            select(TurnRow.status, BotRow.name)
            .join(AgentRow, TurnRow.agent_id == AgentRow.id)
            .join(BotRow, AgentRow.bot_id == BotRow.id)
            .where(TurnRow.status.in_(("done", "failed")))
            .where(TurnRow.finished_at.is_not(None))
            .where(TurnRow.finished_at >= since)
        )
        counts: Counter[str] = Counter()
        failed_bots: list[str] = []
        for status, bot_name in rows:
            counts[status] += 1
            if status == "failed" and bot_name not in failed_bots:
                failed_bots.append(bot_name)
    return counts["done"], counts["failed"], failed_bots


async def _today(
    upcoming: list[FleetRoutine], now: datetime
) -> tuple[list[BriefRoutine], float, int]:
    async with open_session() as session:
        rows = {
            row.id: row
            for row in await session.scalars(select(Routine).where(Routine.status == "active"))
        }
    found: list[BriefRoutine] = []
    total = 0.0
    unpriced = 0
    for item in upcoming:
        row = rows.get(item.id)
        if row is None:
            continue
        try:
            runs = runs_between(parse(row.schedule), now, now + _DAY, ZoneInfo(row.timezone))
        except (ValueError, ZoneInfoNotFoundError):
            continue
        if runs == 0:
            continue
        found.append(
            BriefRoutine(
                id=item.id,
                name=item.name,
                bot_name=item.bot_name,
                next_run=item.next_run,
                runs=runs,
                cost_per_run_usd=item.cost_per_run_usd,
            )
        )
        if item.cost_per_run_usd is None:
            unpriced += 1
        else:
            total += item.cost_per_run_usd * runs
    return found, total, unpriced


def _issues(
    board: FleetOverview,
    metrics: list[FleetMetric],
    now: datetime,
    failed: int,
    failed_bots: list[str],
) -> list[BriefIssue]:
    issues: list[BriefIssue] = []
    if failed:
        turns = "turn" if failed == 1 else "turns"
        issues.append(
            BriefIssue(
                kind="failed_turns",
                text=f"{failed} failed {turns} in the last 24 hours ({', '.join(failed_bots)})",
            )
        )
    for routine in board.upcoming:
        if routine.last_outcome == "failed":
            issues.append(
                BriefIssue(kind="failed_routine", text=f"{routine.name}: the last run failed")
            )
        if routine.status == "paused" and routine.paused_reason == "budget":
            issues.append(
                BriefIssue(kind="paused_by_budget", text=f"{routine.name} paused by budget")
            )
    overdue = sum(1 for item in board.waiting if item.due_by is not None and item.due_by < now)
    if overdue:
        noun = "question" if overdue == 1 else "questions"
        issues.append(BriefIssue(kind="overdue_question", text=f"{overdue} overdue {noun}"))
    for metric in metrics:
        if metric.status == "stale":
            issues.append(
                BriefIssue(kind="stale_metric", text=f"{metric.label} is stale ({metric.source})")
            )
        elif metric.status == "error":
            issues.append(
                BriefIssue(
                    kind="error_metric", text=f"{metric.label} is unavailable ({metric.source})"
                )
            )
        elif metric.status == "conflict":
            issues.append(
                BriefIssue(kind="conflict_metric", text=f"Bots disagree on {metric.label}")
            )
    ollama = board.host.ollama
    if ollama.configured and ollama.reachable is False:
        issues.append(BriefIssue(kind="ollama_down", text=f"Ollama is {ollama.error}"))
    return issues
