"""First host methods: system.info, system.ping, and sync.since (D13)."""

from __future__ import annotations

import asyncio

from sevn import __version__
from sevn.contracts.methods import (
    SyncSinceParams,
    SyncSinceResult,
    SystemCaps,
    SystemInfoParams,
    SystemInfoResult,
    SystemPingParams,
    SystemPingResult,
)
from sevn.protocol import PROTOCOL_VERSION
from sevn.protocol.registry import Ctx, method
from sevn.sandbox.policy import allow_all_enabled


@method("system.info", params=SystemInfoParams, result=SystemInfoResult, mutating=False)
async def system_info(ctx: Ctx, _params: SystemInfoParams) -> SystemInfoResult:
    identity = ctx.hub.identity
    allow_all = await asyncio.to_thread(allow_all_enabled)
    return SystemInfoResult(
        host_id=identity.host_id,
        version=__version__,
        proto=PROTOCOL_VERSION,
        caps=SystemCaps(allow_all=allow_all),
        host_pubkey_fp=identity.host_pubkey_fp,
    )


@method("system.ping", params=SystemPingParams, result=SystemPingResult, mutating=True)
async def system_ping(ctx: Ctx, params: SystemPingParams) -> SystemPingResult:
    event = await ctx.hub.emit("system.ping", "system", {"note": params.note})
    return SystemPingResult(seq=event.seq)


@method("sync.since", params=SyncSinceParams, result=SyncSinceResult, mutating=False)
async def sync_since(ctx: Ctx, params: SyncSinceParams) -> SyncSinceResult:
    page = await ctx.hub.sync_since(ctx, params.seq, limit=params.limit)
    return SyncSinceResult(host_seq=page.host_seq, next_seq=page.next_seq, more=page.more)
