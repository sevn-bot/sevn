"""Startup sweep for turns that died mid-run (D7)."""

from __future__ import annotations

from sqlalchemy import select

from sevn.domain.session import open_session
from sevn.store.models import Job as JobRow
from sevn.store.models import Turn as TurnRow


async def recover() -> None:
    """Requeue ``started`` jobs whose turn has no committed result.

    A ``waiting`` turn stays waiting, and so does its job. A committed
    ``model_messages`` value is a result, including an empty list.
    """
    async with open_session() as session:
        jobs = list(await session.scalars(select(JobRow).where(JobRow.status == "started")))
        if len(jobs) == 0:
            return
        turns = list(await session.scalars(select(TurnRow)))
        for job in jobs:
            related = [turn for turn in turns if job.id in turn.job_ids]
            if any(turn.status == "waiting" for turn in related):
                continue
            if any(turn.model_messages is not None for turn in related):
                continue
            job.status = "queued"
            job.started_at = None
        await session.commit()
