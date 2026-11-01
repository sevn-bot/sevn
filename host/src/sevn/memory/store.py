"""Staged bot memories. A turn's writes land only when that turn commits (D9)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.config import Settings
from sevn.domain.errors import DomainError
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.store.db import utcnow
from sevn.store.models import Memory as MemoryRow

type Tier = Literal["pinned", "recall"]
type Origin = Literal["user", "bot"]


class MemoryRecord(BaseModel):
    """One committed or staged memory."""

    model_config = ConfigDict(extra="forbid")

    id: str
    bot_id: str
    text: str
    tier: Tier
    origin: Origin
    revision: int


@dataclass(slots=True)
class _Batch:
    bot_id: str
    inserts: list[MemoryRecord] = field(default_factory=list[MemoryRecord])
    deletes: list[str] = field(default_factory=list[str])
    tiers: list[tuple[str, str, int]] = field(default_factory=list[tuple[str, str, int]])


_locks: dict[str, asyncio.Lock] = {}
_pending: dict[str, _Batch] = {}


@asynccontextmanager
async def bot_write_lock(bot_id: str) -> AsyncGenerator[None]:
    """Serialize memory writes for one bot. Two bots may proceed together."""
    lock = _locks.get(bot_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[bot_id] = lock
    async with lock:
        yield


class MemoryStore:
    """Pinned and recall memories for one host database."""

    async def save(
        self,
        bot_id: str,
        text: str,
        *,
        tier: str = "recall",
        origin: str = "bot",
        turn_id: str,
    ) -> MemoryRecord:
        """Stage an insert. ``search`` stays empty until ``commit``."""
        chosen = _tier(tier)
        who = _origin(origin)
        async with bot_write_lock(bot_id):
            if chosen == "pinned":
                await _reject_over_budget(bot_id, len(text.encode("utf-8")))
            record = MemoryRecord(
                id=new_id("mem_"),
                bot_id=bot_id,
                text=text,
                tier=chosen,
                origin=who,
                revision=1,
            )
            _batch(turn_id, bot_id).inserts.append(record)
            return record

    async def search(self, bot_id: str, query: str, *, limit: int = 5) -> list[MemoryRecord]:
        """Committed memories whose text matches ``query``. Staged rows are hidden."""
        match = _match_query(query)
        if match is None:
            return []
        statement = text(
            "SELECT memories.id, memories.bot_id, memories.text, memories.tier, "
            "memories.origin, memories.revision "
            "FROM memories JOIN memories_fts ON memories_fts.id = memories.id "
            "WHERE memories.bot_id = :bot_id AND memories_fts MATCH :query "
            "ORDER BY memories.created_at LIMIT :limit"
        )
        try:
            async with open_session() as session:
                result = await session.execute(
                    statement,
                    {"bot_id": bot_id, "query": match, "limit": limit},
                )
                found: list[MemoryRecord] = []
                for row in result.mappings():
                    found.append(_from_mapping(cast("Mapping[str, object]", dict(row))))
                return found
        except OperationalError:
            return []

    async def commit(self, turn_id: str) -> None:
        """Write the turn's staged rows and drop the batch."""
        async with open_session() as session:
            await self.write(session, turn_id)
            await session.commit()

    async def rollback(self, turn_id: str) -> None:
        """Drop staged rows. Nothing is written."""
        _pending.pop(turn_id, None)

    async def write(self, session: AsyncSession, turn_id: str) -> None:
        """Insert the staged batch into ``session`` and remove it from the stage.

        The caller commits ``session``. A failed commit has already dropped the
        batch, so a failed turn keeps none of its memory writes.
        """
        batch = _pending.get(turn_id)
        if batch is None:
            return
        async with bot_write_lock(batch.bot_id):
            current = _pending.pop(turn_id, None)
            if current is None:
                return
            await _apply(session, current)

    async def set_tier(
        self,
        memory_id: str,
        tier: str,
        *,
        actor: str,
        revision: int,
    ) -> MemoryRecord:
        """Change a committed memory's tier. A user origin rejects a bot actor."""
        wanted = _tier(tier)
        current = await self._require(memory_id)
        async with bot_write_lock(current.bot_id):
            fresh = await self._require(memory_id)
            _guard_tier(fresh.origin, fresh.revision, actor=actor, revision=revision)
            if wanted == "pinned" and fresh.tier != "pinned":
                await _reject_over_budget(
                    fresh.bot_id, len(fresh.text.encode("utf-8")), replacing=memory_id
                )
            async with open_session() as session:
                row = await session.get(MemoryRow, memory_id)
                if row is None:
                    raise DomainError("not_found", "memory not found")
                row.tier = wanted
                row.revision += 1
                row.updated_at = utcnow()
                await session.commit()
                return _from_row(row)

    async def update_text(
        self,
        memory_id: str,
        text: str,
        *,
        revision: int | None,
    ) -> MemoryRecord:
        """Replace the text of a committed memory and bump its revision."""
        current = await self._require(memory_id)
        async with bot_write_lock(current.bot_id):
            fresh = await self._require(memory_id)
            if revision is not None and fresh.revision != revision:
                raise DomainError("revision_conflict", "revision conflict")
            if fresh.tier == "pinned":
                extra = len(text.encode("utf-8")) - len(fresh.text.encode("utf-8"))
                if extra > 0:
                    await _reject_over_budget(fresh.bot_id, extra)
            async with open_session() as session:
                row = await session.get(MemoryRow, memory_id)
                if row is None:
                    raise DomainError("not_found", "memory not found")
                row.text = text
                row.revision += 1
                row.updated_at = utcnow()
                await _replace_fts(session, memory_id, text)
                await session.commit()
                return _from_row(row)

    async def delete(self, memory_id: str) -> str:
        """Remove a committed memory and its search row."""
        current = await self._require(memory_id)
        async with bot_write_lock(current.bot_id):
            async with open_session() as session:
                row = await session.get(MemoryRow, memory_id)
                if row is None:
                    raise DomainError("not_found", "memory not found")
                await session.delete(row)
                await session.execute(
                    text("DELETE FROM memories_fts WHERE id = :id"),
                    {"id": memory_id},
                )
                await session.commit()
        return memory_id

    async def pin(
        self,
        memory_id: str,
        *,
        tier: str | None,
        revision: int | None,
    ) -> MemoryRecord:
        """Pin a memory, or set ``tier`` when the caller names one. Actor is the user."""
        current = await self._require(memory_id)
        wanted = "pinned" if tier is None else tier
        rev = current.revision if revision is None else revision
        return await self.set_tier(memory_id, wanted, actor="user", revision=rev)

    async def list_for(self, bot_id: str) -> list[MemoryRecord]:
        """Committed memories for ``bot_id``, oldest first."""
        async with open_session() as session:
            rows = list(
                await session.scalars(
                    select(MemoryRow)
                    .where(MemoryRow.bot_id == bot_id)
                    .order_by(MemoryRow.created_at)
                )
            )
            return [_from_row(row) for row in rows]

    async def stage_delete(self, bot_id: str, memory_id: str, *, turn_id: str) -> None:
        """Stage a delete, or drop an insert from the same turn."""
        async with bot_write_lock(bot_id):
            batch = _batch(turn_id, bot_id)
            kept = [item for item in batch.inserts if item.id != memory_id]
            if len(kept) != len(batch.inserts):
                batch.inserts = kept
                return
            current = await self._require(memory_id)
            if current.bot_id != bot_id:
                raise DomainError("not_found", "memory not found")
            batch.deletes.append(memory_id)

    async def stage_tier(
        self,
        memory_id: str,
        tier: str,
        *,
        actor: str,
        revision: int,
        turn_id: str,
        caller_bot_id: str | None = None,
    ) -> MemoryRecord:
        """Stage a tier change. A user-origin row rejects a bot actor immediately.

        ``caller_bot_id`` scopes the change to that bot: another bot's memory
        is ``not_found``.
        """
        wanted = _tier(tier)
        bot_id = await self._bot_for(memory_id, turn_id)
        if caller_bot_id is not None and bot_id != caller_bot_id:
            raise DomainError("not_found", "memory not found")
        async with bot_write_lock(bot_id):
            batch = _pending.get(turn_id)
            if batch is not None:
                staged = _staged(batch, memory_id)
                if staged is not None:
                    _guard_tier(staged.origin, staged.revision, actor=actor, revision=revision)
                    if wanted == "pinned" and staged.tier != "pinned":
                        await _reject_over_budget(
                            staged.bot_id, len(staged.text.encode("utf-8")), replacing=memory_id
                        )
                    updated = staged.model_copy(update={"tier": wanted, "revision": revision + 1})
                    index = batch.inserts.index(staged)
                    batch.inserts[index] = updated
                    return updated
            current = await self._require(memory_id)
            _guard_tier(current.origin, current.revision, actor=actor, revision=revision)
            if wanted == "pinned" and current.tier != "pinned":
                await _reject_over_budget(
                    current.bot_id, len(current.text.encode("utf-8")), replacing=memory_id
                )
            _batch(turn_id, current.bot_id).tiers.append((memory_id, wanted, revision))
            return current.model_copy(update={"tier": wanted, "revision": revision + 1})

    async def _require(self, memory_id: str) -> MemoryRecord:
        async with open_session() as session:
            row = await session.get(MemoryRow, memory_id)
            if row is None:
                raise DomainError("not_found", "memory not found")
            return _from_row(row)

    async def _bot_for(self, memory_id: str, turn_id: str) -> str:
        batch = _pending.get(turn_id)
        if batch is not None and any(item.id == memory_id for item in batch.inserts):
            return batch.bot_id
        return (await self._require(memory_id)).bot_id


def _batch(turn_id: str, bot_id: str) -> _Batch:
    batch = _pending.get(turn_id)
    if batch is None:
        created = _Batch(bot_id=bot_id)
        _pending[turn_id] = created
        return created
    if batch.bot_id != bot_id:
        raise DomainError("invalid_params", "turn belongs to another bot")
    return batch


def _staged(batch: _Batch, memory_id: str) -> MemoryRecord | None:
    for record in batch.inserts:
        if record.id == memory_id:
            return record
    return None


async def _apply(session: AsyncSession, batch: _Batch) -> None:
    now = utcnow()
    for record in batch.inserts:
        session.add(
            MemoryRow(
                id=record.id,
                bot_id=record.bot_id,
                text=record.text,
                tier=record.tier,
                origin=record.origin,
                revision=record.revision,
                created_at=now,
                updated_at=now,
            )
        )
        await _replace_fts(session, record.id, record.text)
    for memory_id in batch.deletes:
        row = await session.get(MemoryRow, memory_id)
        if row is not None:
            await session.delete(row)
        await session.execute(
            text("DELETE FROM memories_fts WHERE id = :id"),
            {"id": memory_id},
        )
    for memory_id, tier, revision in batch.tiers:
        row = await session.get(MemoryRow, memory_id)
        if row is None:
            continue
        if row.revision != revision:
            raise DomainError("revision_conflict", "revision conflict")
        row.tier = tier
        row.revision += 1
        row.updated_at = utcnow()


async def _replace_fts(session: AsyncSession, memory_id: str, body: str) -> None:
    await session.execute(text("DELETE FROM memories_fts WHERE id = :id"), {"id": memory_id})
    await session.execute(
        text("INSERT INTO memories_fts (id, text) VALUES (:id, :text)"),
        {"id": memory_id, "text": body},
    )


async def _reject_over_budget(bot_id: str, extra: int, *, replacing: str | None = None) -> None:
    if await _pinned_bytes(bot_id, excluding=replacing) + extra > _budget():
        raise DomainError("pinned_budget", "pinned memory budget exceeded")


async def _pinned_bytes(bot_id: str, *, excluding: str | None = None) -> int:
    async with open_session() as session:
        rows = list(await session.scalars(select(MemoryRow).where(MemoryRow.bot_id == bot_id)))
    pinned = {row.id: row.text for row in rows if row.tier == "pinned"}
    texts = {row.id: row.text for row in rows}
    for batch in _pending.values():
        if batch.bot_id != bot_id:
            continue
        for record in batch.inserts:
            if record.tier == "pinned":
                pinned[record.id] = record.text
        # Reserve promotions across all staged turns; do not credit uncommitted
        # demotions/deletes, since that turn may still fail or be cancelled.
        for memory_id, tier, _revision in batch.tiers:
            if tier == "pinned" and memory_id in texts:
                pinned[memory_id] = texts[memory_id]
    return sum(
        len(body.encode("utf-8")) for memory_id, body in pinned.items() if memory_id != excluding
    )


def _budget() -> int:
    return Settings.load().memory.pinned_budget


def _guard_tier(origin: str, current: int, *, actor: str, revision: int) -> None:
    if actor == "bot" and origin == "user":
        raise DomainError("memory_locked", "user memory is locked")
    if current != revision:
        raise DomainError("revision_conflict", "revision conflict")


def _tier(value: str) -> Tier:
    if value == "pinned" or value == "recall":
        return value
    raise DomainError("invalid_params", "unknown memory tier")


def _origin(value: str) -> Origin:
    if value == "user" or value == "bot":
        return value
    raise DomainError("invalid_params", "unknown memory origin")


def _match_query(query: str) -> str | None:
    stripped = query.strip()
    if stripped == "":
        return None
    return '"' + stripped.replace('"', '""') + '"'


def _from_row(row: MemoryRow) -> MemoryRecord:
    return MemoryRecord(
        id=row.id,
        bot_id=row.bot_id,
        text=row.text,
        tier=_tier(row.tier),
        origin=_origin(row.origin),
        revision=row.revision,
    )


def _from_mapping(row: Mapping[str, object]) -> MemoryRecord:
    return MemoryRecord(
        id=_text_cell(row["id"]),
        bot_id=_text_cell(row["bot_id"]),
        text=_text_cell(row["text"]),
        tier=_tier(_text_cell(row["tier"])),
        origin=_origin(_text_cell(row["origin"])),
        revision=_int_cell(row["revision"]),
    )


def _text_cell(value: object) -> str:
    if isinstance(value, str):
        return value
    raise DomainError("invalid_params", "memory row is incomplete")


def _int_cell(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise DomainError("invalid_params", "memory row is incomplete")
