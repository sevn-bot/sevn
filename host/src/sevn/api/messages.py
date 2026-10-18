"""Message and turn protocol methods (D6, D7, D10)."""

from __future__ import annotations

from sevn.api.errors import raise_protocol
from sevn.contracts.methods import (
    MessagesListParams,
    MessagesListResult,
    MessagesSendParams,
    MessagesSendResult,
    TurnsCancelParams,
    TurnsCancelResult,
    TurnsSnapshotParams,
    TurnsSnapshotResult,
)
from sevn.domain.errors import DomainError
from sevn.domain.ids import new_id
from sevn.domain.jobs import JobService, page_messages
from sevn.domain.routing import route_placeholder
from sevn.protocol.registry import Ctx, method
from sevn.runtime.worker import current


@method(
    "messages.send",
    params=MessagesSendParams,
    result=MessagesSendResult,
    mutating=True,
    scope="owner",
)
async def messages_send(ctx: Ctx, params: MessagesSendParams) -> MessagesSendResult:
    job_id = new_id("job_")
    try:
        agent = await route_placeholder(
            params.bot_id,
            text=params.text,
            agent_id=params.agent_id,
            new_agent=params.new_agent,
            origin_job_id=job_id,
        )
        job = await JobService().enqueue(job_id, params.bot_id, agent.id, params.text)
    except DomainError as exc:
        raise_protocol(exc)
    await ctx.hub.emit(
        "job.queued",
        job.id,
        {
            "job_id": job.id,
            "agent_id": job.agent_id,
            "bot_id": job.bot_id,
            "status": "queued",
        },
    )
    worker = current()
    if worker is not None:
        worker.kick(job.agent_id)
    return MessagesSendResult(job_id=job.id, agent_id=job.agent_id)


@method("messages.list", params=MessagesListParams, result=MessagesListResult, mutating=False)
async def messages_list(_ctx: Ctx, params: MessagesListParams) -> MessagesListResult:
    try:
        page = await page_messages(params.bot_id, params.cursor)
    except DomainError as exc:
        raise_protocol(exc)
    return MessagesListResult(messages=page.messages, next_cursor=page.next_cursor)


@method("turns.snapshot", params=TurnsSnapshotParams, result=TurnsSnapshotResult, mutating=False)
async def turns_snapshot(_ctx: Ctx, params: TurnsSnapshotParams) -> TurnsSnapshotResult:
    worker = current()
    if worker is None:
        raise_protocol(DomainError("not_found", "turn not found"))
    try:
        text, status = await worker.snapshot(params.turn_id)
    except DomainError as exc:
        raise_protocol(exc)
    return TurnsSnapshotResult(text=text, status=status)


@method(
    "turns.cancel",
    params=TurnsCancelParams,
    result=TurnsCancelResult,
    mutating=True,
    scope="owner",
)
async def turns_cancel(_ctx: Ctx, params: TurnsCancelParams) -> TurnsCancelResult:
    worker = current()
    if worker is None:
        raise_protocol(DomainError("not_found", "turn not found"))
    try:
        status = await worker.cancel(params.turn_id)
    except DomainError as exc:
        raise_protocol(exc)
    return TurnsCancelResult(turn_id=params.turn_id, status=status)
