"""``routine.silent``: a scheduled run says it found nothing for the owner.

A Claude bot gets no sevn tools, so it says the same by starting its reply
with ``[silent]``.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.domain.session import open_session
from sevn.store.models import Job as JobRow
from sevn.store.models import Turn as TurnRow
from sevn.tools.registry import TurnDeps, register_toolset

SILENT_MARKER = "[silent]"


def is_silent_reply(text: str) -> bool:
    """True when a reply starts with the silent marker."""
    return text.lstrip().lower().startswith(SILENT_MARKER)


async def mark_silent(turn_id: str) -> bool:
    """Mark the routine jobs of ``turn_id`` silent. False when it runs no routine."""
    async with open_session() as session:
        turn = await session.get(TurnRow, turn_id)
        if turn is None or len(turn.job_ids) == 0:
            return False
        marked = await mark_jobs_silent(session, list(turn.job_ids))
        await session.commit()
        return marked


async def mark_jobs_silent(session: AsyncSession, job_ids: Sequence[str]) -> bool:
    """Mark the routine jobs among ``job_ids`` silent. The caller commits."""
    jobs = list(
        await session.scalars(
            select(JobRow).where(JobRow.id.in_(list(job_ids))).where(JobRow.routine_id.is_not(None))
        )
    )
    for job in jobs:
        job.silent = True
    return len(jobs) > 0


def routine_toolset(deps: TurnDeps) -> dict[str, object]:
    """The silent tool for one turn."""

    async def silent() -> str:
        """Call on a scheduled routine run when nothing needs the owner.

        The run still finishes. The dashboard counts it as a run with no
        useful output, which helps the owner find routines worth cancelling.
        """
        if await mark_silent(deps.turn_id):
            return "ok"
        return "not a routine run"

    return {"routine.silent": silent}


register_toolset("routine", routine_toolset, {"routine.silent"})
