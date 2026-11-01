"""``routine.silent``: a scheduled run says it found nothing for the owner."""

from __future__ import annotations

from sqlalchemy import select

from sevn.domain.session import open_session
from sevn.store.models import Job as JobRow
from sevn.store.models import Turn as TurnRow
from sevn.tools.registry import TurnDeps, register_toolset


async def mark_silent(turn_id: str) -> bool:
    """Mark the routine jobs of ``turn_id`` silent. False when it runs no routine."""
    async with open_session() as session:
        turn = await session.get(TurnRow, turn_id)
        if turn is None or len(turn.job_ids) == 0:
            return False
        jobs = list(
            await session.scalars(
                select(JobRow)
                .where(JobRow.id.in_(list(turn.job_ids)))
                .where(JobRow.routine_id.is_not(None))
            )
        )
        for job in jobs:
            job.silent = True
        await session.commit()
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
