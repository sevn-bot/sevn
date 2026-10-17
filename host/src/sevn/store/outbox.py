"""Durable event outbox (D10)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sevn.contracts.errors import ProtocolError
from sevn.store.db import async_engine, utcnow
from sevn.store.models import Event


class ResyncRequired(ProtocolError):
    """`since` was asked for a seq older than the retained window."""

    def __init__(self, min_seq: int) -> None:
        self.min_seq = min_seq
        super().__init__(
            "resync_required",
            "event history was pruned",
            {"min_seq": min_seq},
        )


class Outbox:
    def __init__(self, url: str) -> None:
        self._engine = async_engine(url)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)
        self._write = asyncio.Lock()

    async def append(self, type: str, entity: str, payload: Mapping[str, object]) -> Event:
        async with self._write:
            async with self._sessions() as session:
                event = Event(
                    type=type,
                    entity=entity,
                    payload=dict(payload),
                    created_at=utcnow(),
                )
                session.add(event)
                await session.commit()
                session.expunge(event)
                return event

    async def since(self, seq: int) -> list[Event]:
        async with self._sessions() as session:
            retained = await _min_seq(session)
            if retained is not None and seq < retained - 1:
                raise ResyncRequired(retained)
            rows = list(
                await session.scalars(select(Event).where(Event.seq > seq).order_by(Event.seq))
            )
            for row in rows:
                session.expunge(row)
            return rows

    async def prune(self, max_age: timedelta, max_rows: int) -> None:
        cutoff = utcnow() - max_age
        async with self._write:
            async with self._sessions() as session, session.begin():
                await session.execute(delete(Event).where(Event.created_at < cutoff))
                if max_rows <= 0:
                    await session.execute(delete(Event))
                    return
                kept = list(
                    await session.scalars(
                        select(Event.seq).order_by(Event.seq.desc()).limit(max_rows)
                    )
                )
                if kept:
                    await session.execute(delete(Event).where(Event.seq < min(kept)))

    async def min_seq(self) -> int | None:
        async with self._sessions() as session:
            return await _min_seq(session)

    async def aclose(self) -> None:
        await self._engine.dispose()


async def _min_seq(session: AsyncSession) -> int | None:
    value = await session.scalar(select(func.min(Event.seq)))
    if value is None:
        return None
    return int(value)
