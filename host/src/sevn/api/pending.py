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
from sevn.domain.routing import answer_question
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
        kind = await PendingService().kind_of(params.pending_id)
    except DomainError as exc:
        raise_protocol(exc)
    if kind == "question":
        return await _answer_question(ctx, params)
    if params.answer is None or params.option_id is not None or params.text is not None:
        raise_protocol(DomainError("invalid_params", "an approval takes approve or deny"))
    decision = params.answer
    try:
        record = await PendingService().resolve(params.pending_id, decision)
    except DomainError as exc:
        raise_protocol(exc)
    claude = await release_permission(record.id, decision)
    waiting = False if claude else await PendingService().has_waiting(record.turn_id)
    worker = current()
    if not claude and not waiting and worker is None:
        raise_protocol(DomainError("not_found", "pending request not found"))
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
    if claude or waiting or worker is None:
        return PendingAnswerResult(id=record.id, status=record.status)
    pairs = await PendingService().decisions(record.turn_id)
    decisions = tuple(ToolDecision(tool_call_id=call_id, approved=ok) for call_id, ok in pairs)
    worker.start_resume(record.agent_id, record.turn_id, decisions)
    return PendingAnswerResult(id=record.id, status=record.status)


async def _answer_question(ctx: Ctx, params: PendingAnswerParams) -> PendingAnswerResult:
    """Close a ``user.ask`` question and queue the answer as the lane's next message."""
    if params.answer is not None:
        raise_protocol(DomainError("invalid_params", "a question takes option_id or text"))
    try:
        job_id, agent_id, turn_id = await answer_question(
            params.pending_id,
            option_id=params.option_id,
            text=params.text,
            hub=ctx.hub,
        )
    except DomainError as exc:
        raise_protocol(exc)
    await ctx.hub.emit(
        "pending.resolved",
        params.pending_id,
        {
            "pending_id": params.pending_id,
            "turn_id": turn_id,
            "agent_id": agent_id,
            "status": "resolved",
        },
    )
    return PendingAnswerResult(id=params.pending_id, status="resolved", job_id=job_id)
