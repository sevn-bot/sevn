"""Memory protocol methods for the bot settings panel (D9, D18)."""

from __future__ import annotations

from sevn.api.errors import raise_protocol
from sevn.contracts.methods import (
    MemoriesDeleteParams,
    MemoriesDeleteResult,
    MemoriesListParams,
    MemoriesListResult,
    MemoriesPinParams,
    MemoriesUpdateParams,
)
from sevn.domain.errors import DomainError
from sevn.memory.store import MemoryRecord, MemoryStore
from sevn.protocol.registry import Ctx, method


@method("memories.list", params=MemoriesListParams, result=MemoriesListResult, mutating=False)
async def memories_list(_ctx: Ctx, params: MemoriesListParams) -> MemoriesListResult:
    return MemoriesListResult(memories=await MemoryStore().list_for(params.bot_id))


@method(
    "memories.update",
    params=MemoriesUpdateParams,
    result=MemoryRecord,
    mutating=True,
    scope="owner",
)
async def memories_update(ctx: Ctx, params: MemoriesUpdateParams) -> MemoryRecord:
    try:
        record = await MemoryStore().update_text(
            params.id,
            params.text,
            revision=params.revision,
        )
    except DomainError as exc:
        raise_protocol(exc)
    await _changed(ctx, record, "update")
    return record


@method(
    "memories.delete",
    params=MemoriesDeleteParams,
    result=MemoriesDeleteResult,
    mutating=True,
    scope="owner",
)
async def memories_delete(ctx: Ctx, params: MemoriesDeleteParams) -> MemoriesDeleteResult:
    try:
        memory_id = await MemoryStore().delete(params.id)
    except DomainError as exc:
        raise_protocol(exc)
    await ctx.hub.emit("memory.changed", memory_id, {"id": memory_id, "action": "delete"})
    return MemoriesDeleteResult(id=memory_id)


@method(
    "memories.pin",
    params=MemoriesPinParams,
    result=MemoryRecord,
    mutating=True,
    scope="owner",
)
async def memories_pin(ctx: Ctx, params: MemoriesPinParams) -> MemoryRecord:
    try:
        record = await MemoryStore().pin(
            params.id,
            tier=params.tier,
            revision=params.revision,
        )
    except DomainError as exc:
        raise_protocol(exc)
    await _changed(ctx, record, "pin")
    return record


async def _changed(ctx: Ctx, record: MemoryRecord, action: str) -> None:
    await ctx.hub.emit(
        "memory.changed",
        record.id,
        {"id": record.id, "bot_id": record.bot_id, "action": action},
    )
