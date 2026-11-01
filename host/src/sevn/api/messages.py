"""Message and turn protocol methods (D6, D7, D10)."""

from __future__ import annotations

from sevn.api.errors import raise_protocol
from sevn.contracts.methods import (
    MessagesListParams,
    MessagesListResult,
    MessagesRerouteParams,
    MessagesRerouteResult,
    MessagesSendParams,
    MessagesSendResult,
    TurnsCancelParams,
    TurnsCancelResult,
    TurnsSnapshotParams,
    TurnsSnapshotResult,
)
from sevn.domain.errors import DomainError
from sevn.domain.ids import new_id
from sevn.domain.jobs import page_messages
from sevn.domain.routing import RoutedMessage, deliver, reroute
from sevn.protocol.registry import Ctx, method
from sevn.runtime.worker import current
from sevn.store.db import utcnow


@method(
    "messages.send",
    params=MessagesSendParams,
    result=MessagesSendResult,
    mutating=True,
    scope="owner",
)
async def messages_send(ctx: Ctx, params: MessagesSendParams) -> MessagesSendResult:
    job_id = new_id("job_")
    message = RoutedMessage(
        text=params.text,
        author="user",
        created_at=utcnow(),
        source="user",
        new_agent=params.new_agent,
        reply_to=None,
        reply_to_agent_id=None,
        agent_id=params.agent_id,
        bot_id=params.bot_id,
    )
    try:
        stored_job, agent_id = await deliver(message, "user", job_id=job_id, hub=ctx.hub)
    except DomainError as exc:
        raise_protocol(exc)
    return MessagesSendResult(job_id=stored_job, agent_id=agent_id)


@method(
    "messages.reroute",
    params=MessagesRerouteParams,
    result=MessagesRerouteResult,
    mutating=True,
    scope="owner",
)
async def messages_reroute(ctx: Ctx, params: MessagesRerouteParams) -> MessagesRerouteResult:
    try:
        job_id, agent_id = await reroute(
            params.message_id,
            agent_id=params.agent_id,
            start_new=params.new,
            hub=ctx.hub,
        )
    except DomainError as exc:
        raise_protocol(exc)
    return MessagesRerouteResult(job_id=job_id, agent_id=agent_id)


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
