"""``devices.*`` protocol methods (plan 0055 D2)."""

from __future__ import annotations

from sevn.contracts.methods import (
    DevicesListParams,
    DevicesListResult,
    DevicesRenameParams,
    DevicesRevokeParams,
    DevicesSelfParams,
)
from sevn.identity import devices
from sevn.identity.devices import DeviceError, DeviceRecord
from sevn.protocol.registry import Ctx, method


@method(
    "devices.list",
    params=DevicesListParams,
    result=DevicesListResult,
    mutating=False,
    scope="owner",
)
async def devices_list(_ctx: Ctx, _params: DevicesListParams) -> DevicesListResult:
    return DevicesListResult(devices=await devices.list_devices())


@method(
    "devices.rename",
    params=DevicesRenameParams,
    result=DeviceRecord,
    mutating=True,
    scope="owner",
)
async def devices_rename(_ctx: Ctx, params: DevicesRenameParams) -> DeviceRecord:
    return await devices.rename(params.id, params.name)


@method(
    "devices.revoke",
    params=DevicesRevokeParams,
    result=DeviceRecord,
    mutating=True,
    scope="owner",
)
async def devices_revoke(ctx: Ctx, params: DevicesRevokeParams) -> DeviceRecord:
    # Only a loopback owner may revoke the last live owner device (recovery stays local).
    revoked = await devices.revoke(params.id, allow_last_owner=ctx.loopback)
    # D2: revoked_at is committed first, then every live session of the device is cut off.
    await ctx.hub.close_device(revoked.id)
    return revoked


@method(
    "devices.self",
    params=DevicesSelfParams,
    result=DeviceRecord,
    mutating=False,
)
async def devices_self(ctx: Ctx, _params: DevicesSelfParams) -> DeviceRecord:
    device_id = ctx.device_id
    if device_id is None or device_id == "":
        raise DeviceError("not_found", "this session has no paired device")
    return await devices.get_device(device_id)
