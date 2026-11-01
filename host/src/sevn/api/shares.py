"""Share link protocol methods (plan fleet-dashboards, phase 6). Owner only."""

from __future__ import annotations

from sevn.api.errors import raise_protocol
from sevn.contracts.methods import (
    SharesCreateParams,
    SharesCreateResult,
    SharesListParams,
    SharesListResult,
    SharesRevokeParams,
)
from sevn.domain.errors import DomainError
from sevn.domain.shares import ShareRecord, ShareService
from sevn.protocol.registry import Ctx, method


@method(
    "shares.create",
    params=SharesCreateParams,
    result=SharesCreateResult,
    mutating=True,
    scope="owner",
)
async def shares_create(_ctx: Ctx, params: SharesCreateParams) -> SharesCreateResult:
    try:
        record, path = await ShareService().create(
            label=params.label,
            bot_id=params.bot_id,
            expires_in_hours=params.expires_in_hours,
        )
    except DomainError as exc:
        raise_protocol(exc)
    return SharesCreateResult(share=record, path=path)


@method(
    "shares.list",
    params=SharesListParams,
    result=SharesListResult,
    mutating=False,
    scope="owner",
)
async def shares_list(_ctx: Ctx, _params: SharesListParams) -> SharesListResult:
    return SharesListResult(shares=await ShareService().list())


@method(
    "shares.revoke",
    params=SharesRevokeParams,
    result=ShareRecord,
    mutating=True,
    scope="owner",
)
async def shares_revoke(_ctx: Ctx, params: SharesRevokeParams) -> ShareRecord:
    try:
        return await ShareService().revoke(params.share_id)
    except DomainError as exc:
        raise_protocol(exc)
