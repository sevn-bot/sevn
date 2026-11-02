"""Paired devices: list, rename, revoke (plan 0055 D2).

The protocol methods (``sevn.api.devices``) and the offline CLI (``sevn devices``)
share these functions. Revocation only sets ``revoked_at``; closing the device's
live sessions is the hub's job.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy import CursorResult, func, or_, select, update

from sevn.contracts.errors import ErrorCode, ProtocolError
from sevn.domain.session import open_session
from sevn.protocol.errors import Scope
from sevn.store.db import utcnow
from sevn.store.models import Device

NAME_LIMIT = 80
PLATFORM_LIMIT = 32
_SCOPES: frozenset[str] = frozenset({"owner", "member", "read_only"})


class DeviceError(ProtocolError):
    """A refused device operation (``not_found``, ``invalid_params``, ``last_owner``)."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(code, message)


class DeviceRecord(BaseModel):
    """A paired device as the owner sees it. Keys are not part of the record."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    platform: str
    scope: Scope
    created_at: datetime
    last_seen: datetime | None
    revoked_at: datetime | None


def clean_name(raw: str, *, limit: int = NAME_LIMIT) -> str:
    return " ".join(raw.split())[:limit]


async def list_devices() -> list[DeviceRecord]:
    async with open_session() as session:
        rows = await session.scalars(select(Device).order_by(Device.created_at, Device.id))
        return [record(row) for row in rows]


async def get_device(device_id: str) -> DeviceRecord:
    async with open_session() as session:
        row = await session.get(Device, device_id)
        if row is None:
            raise _not_found(device_id)
        return record(row)


async def rename(device_id: str, name: str) -> DeviceRecord:
    cleaned = clean_name(name)
    if cleaned == "":
        raise DeviceError("invalid_params", "device name is empty")
    async with open_session() as session:
        row = await session.get(Device, device_id)
        if row is None:
            raise _not_found(device_id)
        row.name = cleaned
        await session.commit()
        return record(row)


async def revoke(device_id: str, *, allow_last_owner: bool) -> DeviceRecord:
    """Set ``revoked_at``. Revoking a revoked device returns it unchanged.

    Without ``allow_last_owner`` (any non-loopback caller) the last live owner
    device stays, so the owner keeps a way back in from outside. The check and
    the update are one statement, so two racing revokes cannot both pass it.
    """
    now = utcnow()
    stmt = update(Device).where(Device.id == device_id).where(Device.revoked_at.is_(None))
    if not allow_last_owner:
        live_owners = (
            select(func.count())
            .select_from(Device)
            .where(Device.scope == "owner")
            .where(Device.revoked_at.is_(None))
            .scalar_subquery()
        )
        stmt = stmt.where(or_(Device.scope != "owner", live_owners > 1))
    async with open_session() as session:
        updated = cast(
            "CursorResult[Any]",
            await session.execute(stmt.values(revoked_at=now)),
        )
        await session.commit()
        row = await session.get(Device, device_id, populate_existing=True)
        if row is None:
            raise _not_found(device_id)
        if updated.rowcount != 1 and row.revoked_at is None:
            raise DeviceError("last_owner", "cannot revoke the last owner device")
        return record(row)


def record(row: Device) -> DeviceRecord:
    scope = row.scope
    if scope not in _SCOPES:
        raise ValueError(f"device {row.id} has an unknown scope")
    return DeviceRecord(
        id=row.id,
        name=row.name,
        platform=row.platform,
        scope=cast("Scope", scope),
        created_at=row.created_at,
        last_seen=row.last_seen,
        revoked_at=row.revoked_at,
    )


def _not_found(device_id: str) -> DeviceError:
    return DeviceError("not_found", f"device not found: {device_id}")
