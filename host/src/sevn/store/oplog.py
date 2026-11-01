"""Idempotency op log, retained for 24 hours (D11)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from sevn.store.db import async_engine, utcnow
from sevn.store.models import OpLogEntry

_RETENTION = timedelta(hours=24)


class OpLog:
    def __init__(self, url: str) -> None:
        self._engine = async_engine(url)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    async def record(self, op_id: str, method: str, result: Mapping[str, object]) -> None:
        async with self._sessions() as session:
            session.add(
                OpLogEntry(
                    op_id=op_id,
                    method=method,
                    result=dict(result),
                    created_at=utcnow(),
                )
            )
            await session.commit()

    async def lookup(self, op_id: str) -> OpLogEntry | None:
        async with self._sessions() as session:
            found = await session.get(OpLogEntry, op_id)
            if found is None:
                return None
            if _aware(found.created_at) < utcnow() - _RETENTION:
                return None
            session.expunge(found)
            return found

    async def replace_result(self, op_id: str, result: Mapping[str, object]) -> None:
        async with self._sessions() as session:
            found = await session.get(OpLogEntry, op_id)
            if found is None:
                return
            found.result = dict(result)
            await session.commit()

    async def forget_pending(self, op_id: str) -> None:
        """Drop the in-progress marker for ``op_id``. A finished result stays."""
        async with self._sessions() as session:
            found = await session.get(OpLogEntry, op_id)
            if found is None or found.result.get("_pending") is not True:
                return
            await session.delete(found)
            await session.commit()

    async def prune(self) -> None:
        cutoff = utcnow() - _RETENTION
        async with self._sessions() as session, session.begin():
            await session.execute(delete(OpLogEntry).where(OpLogEntry.created_at < cutoff))

    async def aclose(self) -> None:
        await self._engine.dispose()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
