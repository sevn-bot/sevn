"""Routine protocol methods (plan fleet-dashboards, phase 4)."""

from __future__ import annotations

from collections.abc import Awaitable

from sevn.api.errors import raise_protocol
from sevn.contracts.methods import (
    RoutineIdParams,
    RoutinesCreateParams,
    RoutinesListParams,
    RoutinesListResult,
    RoutinesUpdateParams,
)
from sevn.domain.errors import DomainError
from sevn.domain.routines import RoutineRecord, RoutineService, routine_event
from sevn.protocol.registry import Ctx, method


@method("routines.list", params=RoutinesListParams, result=RoutinesListResult, mutating=False)
async def routines_list(_ctx: Ctx, params: RoutinesListParams) -> RoutinesListResult:
    found = await RoutineService().list(params.bot_id, include_cancelled=params.include_cancelled)
    return RoutinesListResult(routines=found)


@method(
    "routines.create",
    params=RoutinesCreateParams,
    result=RoutineRecord,
    mutating=True,
    scope="owner",
)
async def routines_create(ctx: Ctx, params: RoutinesCreateParams) -> RoutineRecord:
    return await _changed(
        ctx,
        RoutineService().create(
            params.bot_id,
            name=params.name,
            schedule=params.schedule,
            timezone=params.timezone,
            text=params.text,
        ),
    )


@method(
    "routines.update",
    params=RoutinesUpdateParams,
    result=RoutineRecord,
    mutating=True,
    scope="owner",
)
async def routines_update(ctx: Ctx, params: RoutinesUpdateParams) -> RoutineRecord:
    return await _changed(
        ctx,
        RoutineService().update(
            params.routine_id,
            name=params.name,
            schedule=params.schedule,
            timezone=params.timezone,
            text=params.text,
        ),
    )


@method(
    "routines.pause", params=RoutineIdParams, result=RoutineRecord, mutating=True, scope="owner"
)
async def routines_pause(ctx: Ctx, params: RoutineIdParams) -> RoutineRecord:
    return await _changed(ctx, RoutineService().pause(params.routine_id))


@method(
    "routines.resume", params=RoutineIdParams, result=RoutineRecord, mutating=True, scope="owner"
)
async def routines_resume(ctx: Ctx, params: RoutineIdParams) -> RoutineRecord:
    return await _changed(ctx, RoutineService().resume(params.routine_id))


@method(
    "routines.cancel", params=RoutineIdParams, result=RoutineRecord, mutating=True, scope="owner"
)
async def routines_cancel(ctx: Ctx, params: RoutineIdParams) -> RoutineRecord:
    return await _changed(ctx, RoutineService().cancel(params.routine_id))


async def _changed(ctx: Ctx, work: Awaitable[RoutineRecord]) -> RoutineRecord:
    try:
        record = await work
    except DomainError as exc:
        raise_protocol(exc)
    await ctx.hub.emit("routine.updated", record.id, routine_event(record))
    return record
