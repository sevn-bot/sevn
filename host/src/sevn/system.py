"""First host methods: system.info, system.ping, and sync.since (D13)."""

from __future__ import annotations

from sevn import __version__
from sevn.contracts.methods import (
    SyncSinceParams,
    SyncSinceResult,
    SystemInfoParams,
    SystemInfoResult,
    SystemPingParams,
    SystemPingResult,
)
from sevn.protocol import HOST_CAPS, PROTOCOL_VERSION
from sevn.protocol.registry import Ctx, method


@method("system.info", params=SystemInfoParams, result=SystemInfoResult, mutating=False)
async def system_info(ctx: Ctx, _params: SystemInfoParams) -> SystemInfoResult:
    identity = ctx.hub.identity
    return SystemInfoResult(
        host_id=identity.host_id,
        version=__version__,
        proto=PROTOCOL_VERSION,
        caps=list(HOST_CAPS),
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
