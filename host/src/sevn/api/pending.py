"""Approval protocol methods (D8, D10)."""

from __future__ import annotations

from sevn.api.errors import raise_protocol
from sevn.contracts.methods import (
    PendingAnswerParams,
    PendingAnswerResult,
    PendingListParams,
    PendingListResult,
)
from sevn.domain.errors import DomainError
from sevn.domain.pending import PendingService
from sevn.protocol.registry import Ctx, method
from sevn.runtime.base import ToolDecision
from sevn.runtime.runtimes.claude import release_permission
from sevn.runtime.worker import current


@method("pending.list", params=PendingListParams, result=PendingListResult, mutating=False)
async def pending_list(_ctx: Ctx, _params: PendingListParams) -> PendingListResult:
    return PendingListResult(pending=await PendingService().list_waiting())


@method(
    "pending.answer",
    params=PendingAnswerParams,
    result=PendingAnswerResult,
    mutating=True,
    scope="owner",
)
async def pending_answer(ctx: Ctx, params: PendingAnswerParams) -> PendingAnswerResult:
    try:
        record = await PendingService().resolve(params.pending_id, params.answer)
    except DomainError as exc:
        raise_protocol(exc)
    await ctx.hub.emit(
        "pending.resolved",
        record.id,
        {
            "pending_id": record.id,
            "turn_id": record.turn_id,
            "agent_id": record.agent_id,
            "status": "resolved",
        },
    )
    if await release_permission(record.id, params.answer):
        return PendingAnswerResult(id=record.id, status=record.status)
    if await PendingService().has_waiting(record.turn_id):
        return PendingAnswerResult(id=record.id, status=record.status)
    worker = current()
    if worker is None:
        raise_protocol(DomainError("not_found", "pending request not found"))
    pairs = await PendingService().decisions(record.turn_id)
    decisions = tuple(ToolDecision(tool_call_id=call_id, approved=ok) for call_id, ok in pairs)
    await worker.resume(record.agent_id, record.turn_id, decisions)
    return PendingAnswerResult(id=record.id, status=record.status)
