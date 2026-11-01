"""How a turn ends early: failure records and the three cancel paths."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.domain.ids import new_id
from sevn.domain.pending import latest_response_tool_call_ids
from sevn.domain.session import open_session
from sevn.domain.workspace import drop_locks
from sevn.log import logger
from sevn.memory.store import MemoryStore
from sevn.protocol.hub import Hub
from sevn.runtime.errors import ModelError, TurnError
from sevn.runtime.turn_store import (
    agent_event,
    finish_job,
    has_user_message,
    job_event,
    message_event,
    resolve_open_pendings,
    set_agent,
    text_parts,
    turn_event,
)
from sevn.runtime.usage import combine as combine_usage
from sevn.runtime.usage import interrupted_usage
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import Event, Message
from sevn.store.models import Job as JobRow
from sevn.store.models import PendingRequest as PendingRow
from sevn.store.models import Turn as TurnRow

_TERMINAL = frozenset({"done", "cancelled", "failed", "interrupted"})


_FAILED = "This turn failed."


def failure_text(partial: str) -> str:
    """Chat text for a runtime error. Streamed text stays; the notice is fixed."""
    if partial == "":
        return _FAILED
    return f"{partial}\n{_FAILED}"


async def record_turn_failure(
    hub: Hub,
    exc: BaseException,
    *,
    job_id: str | None = None,
    turn_id: str | None = None,
) -> None:
    """Finish a turn that raised after it started, and show that to the client.

    A turn already committed as ``done`` or still paused on an open approval
    is left alone. Anything else becomes ``failed``, the job leaves the
    queue, and the agent returns to ``idle``.
    """
    notice = _failure_notice(exc)
    async with open_session() as session:
        job, turn = await _failure_rows(session, job_id, turn_id)
        if _leave_failure_alone(turn) or (
            turn is not None
            and turn.status == "waiting"
            and await _has_waiting_pending(session, turn.id)
        ):
            return
        now = utcnow()
        events: list[Event] = []
        if job is not None and job.status in {"queued", "started"}:
            job.status = "failed"
            job.finished_at = now
            if job.agent_id is not None:
                events.append(job_event("job.done", job.id, job.agent_id, "failed"))
        if turn is not None and turn.status in {"running", "waiting"}:
            events.extend(
                await _fail_open_turn(session, turn, job, notice, now, usage=_failed_usage(exc))
            )
        agent_id = turn.agent_id if turn is not None else None
        if agent_id is None and job is not None:
            agent_id = job.agent_id
        if agent_id is not None:
            failed_id = turn.id if turn is not None else None
            status = await _sync_agent_status(session, agent_id, failed_id, now)
            if status is not None:
                events.append(agent_event(agent_id, status))
        for event in events:
            session.add(event)
        await session.commit()
        for event in events:
            try:
                await hub.relay(event)
            except Exception:  # noqa: BLE001 — the row is committed; delivery can fail alone
                logger.exception("turn failure event was not delivered")


def _failure_notice(exc: BaseException) -> str:
    """Text safe to store. Provider errors can echo the prompt."""
    if isinstance(exc, ModelError | TurnError) and exc.message != "":
        return exc.message
    return _FAILED


def _leave_failure_alone(turn: TurnRow | None) -> bool:
    return turn is not None and turn.status in _TERMINAL


async def _failure_rows(
    session: AsyncSession,
    job_id: str | None,
    turn_id: str | None,
) -> tuple[JobRow | None, TurnRow | None]:
    turn = await session.get(TurnRow, turn_id) if turn_id is not None else None
    if job_id is None and turn is not None and len(turn.job_ids) > 0:
        job_id = turn.job_ids[0]
    job = await session.get(JobRow, job_id) if job_id is not None else None
    if turn is None and job is not None and job.agent_id is not None and job_id is not None:
        turn = await _open_turn_for_job(session, job.agent_id, job_id)
    return job, turn


async def _open_turn_for_job(session: AsyncSession, agent_id: str, job_id: str) -> TurnRow | None:
    rows = await session.scalars(
        select(TurnRow)
        .where(TurnRow.agent_id == agent_id)
        .where(TurnRow.status.in_(("running", "waiting")))
    )
    for row in rows:
        if job_id in row.job_ids:
            return row
    return None


def _failed_usage(exc: BaseException) -> dict[str, object]:
    """What the failed run used, or an unknown marker when nothing reported it."""
    if isinstance(exc, TurnError) and exc.usage is not None:
        return exc.usage
    return interrupted_usage()


async def _has_waiting_pending(session: AsyncSession, turn_id: str) -> bool:
    found = await session.scalar(
        select(PendingRow.id)
        .where(PendingRow.turn_id == turn_id)
        .where(PendingRow.status == "waiting")
        .limit(1)
    )
    return found is not None


async def _fail_open_turn(
    session: AsyncSession,
    turn: TurnRow,
    job: JobRow | None,
    notice: str,
    now: datetime,
    *,
    usage: dict[str, object],
) -> list[Event]:
    turn.status = "failed"
    turn.finished_at = now
    # Earlier runs of a resumed turn keep their usage; the failed run adds its own.
    turn.usage = combine_usage(turn.usage or {}, usage)
    turn.model_messages = None
    events = await resolve_open_pendings(session, turn, now)
    if job is not None and not await has_user_message(session, turn.id):
        user = Message(
            id=new_id("msg_"),
            thread_id=turn.thread_id,
            turn_id=turn.id,
            agent_id=turn.agent_id,
            role="user",
            author="user",
            parts=text_parts(job.text),
            created_at=turn.started_at,
        )
        session.add(user)
        events.append(message_event(user))
    author = job.to_bot_id if job is not None else "system"
    assistant = Message(
        id=new_id("msg_"),
        thread_id=turn.thread_id,
        turn_id=turn.id,
        agent_id=turn.agent_id,
        role="assistant",
        author=author,
        parts=text_parts(notice),
        created_at=now,
    )
    session.add(assistant)
    events.append(message_event(assistant))
    events.append(turn_event("turn.finished", turn.id, turn.agent_id, "failed"))
    await drop_locks(session, turn.agent_id)
    return events


async def persist_running_cancel(hub: Hub, turn_id: str) -> bool:
    """Store cancel for a turn whose model stream is still open.

    The in-memory flag is lost if the host stops. Recovery would otherwise
    mark the running turn failed and queue the same request again.
    Returns true when this call wrote ``cancelled``.
    """
    finished_at = utcnow()
    async with open_session() as session:
        turn = await session.get(TurnRow, turn_id)
        if turn is None or turn.status != "running":
            return False
        job_id = turn.job_ids[0] if len(turn.job_ids) > 0 else None
        job = await session.get(JobRow, job_id) if job_id is not None else None
        turn.status = "cancelled"
        turn.finished_at = finished_at
        # The open run never reported its usage; earlier runs keep theirs.
        turn.usage = combine_usage(turn.usage or {}, interrupted_usage())
        turn.model_messages = None
        events: list[Event] = []
        if job is not None and not await has_user_message(session, turn.id):
            user = Message(
                id=new_id("msg_"),
                thread_id=turn.thread_id,
                turn_id=turn.id,
                agent_id=turn.agent_id,
                role="user",
                author="user",
                parts=text_parts(job.text),
                created_at=turn.started_at,
            )
            session.add(user)
            events.append(message_event(user))
        for owned_id in turn.job_ids:
            await finish_job(session, owned_id, "cancelled", finished_at)
        await set_agent(session, turn.agent_id, "idle", finished_at)
        await drop_locks(session, turn.agent_id)
        events.append(turn_event("turn.finished", turn.id, turn.agent_id, "cancelled"))
        events.extend(
            job_event("job.done", owned_id, turn.agent_id, "cancelled") for owned_id in turn.job_ids
        )
        events.append(agent_event(turn.agent_id, "idle"))
        events.extend(await resolve_open_pendings(session, turn, finished_at))
        for event in events:
            session.add(event)
        await session.commit()
        for event in events:
            await hub.relay(event)
    return True


async def persist_queued_cancel(hub: Hub, turn_id: str) -> bool:
    """Cancel a turn that has not started, so the pump never runs its jobs.

    Routing stores a ``queued`` turn with the user message before the job runs.
    Returns true when this call wrote ``cancelled``.
    """
    finished_at = utcnow()
    async with open_session() as session:
        turn = await session.get(TurnRow, turn_id)
        if turn is None or turn.status != "queued":
            return False
        turn.status = "cancelled"
        turn.finished_at = finished_at
        events = [turn_event("turn.finished", turn.id, turn.agent_id, "cancelled")]
        for owned_id in turn.job_ids:
            await finish_job(session, owned_id, "cancelled", finished_at)
            events.append(job_event("job.done", owned_id, turn.agent_id, "cancelled"))
        for event in events:
            session.add(event)
        await session.commit()
        for event in events:
            await hub.relay(event)
    return True


async def close_question_turns(session: AsyncSession, agent_id: str, now: datetime) -> None:
    """Close the agent's turns paused on a question once the user has answered.

    The answer runs as the next turn, so a paused turn's staged memory writes
    commit here, in the caller's session, or they are lost. The caller commits.
    """
    turns = list(
        await session.scalars(
            select(TurnRow).where(TurnRow.agent_id == agent_id).where(TurnRow.status == "waiting")
        )
    )
    for turn in turns:
        # A mixed question/approval run must resume its deferred calls instead
        # of publishing an unfinished checkpoint as a completed conversation.
        calls = latest_response_tool_call_ids(turn.model_messages)
        approvals = select(PendingRow.id).where(
            PendingRow.turn_id == turn.id, PendingRow.kind == "approval"
        )
        if calls is not None:
            approvals = approvals.where(PendingRow.tool_call_id.in_(calls))
        approval = await session.scalar(approvals.limit(1))
        if approval is not None or await _has_waiting_pending(session, turn.id):
            continue
        turn.status = "done"
        turn.finished_at = now
        await MemoryStore().write(session, turn.id)
        await drop_locks(session, agent_id)
        for job_id in turn.job_ids or ():
            job = await session.get(JobRow, job_id)
            if job is not None and job.status in ("queued", "started"):
                job.status = "done"
                job.finished_at = now


async def cancel_persisted_waiting(hub: Hub, turn_id: str) -> bool:
    """Cancel a turn already stored as waiting.

    The stream that produced the approval has finished, so the in-memory
    cancel flag and ``Runtime.interrupt`` never reach it. Returns true when
    this call wrote ``cancelled``.
    """
    finished_at = utcnow()
    async with open_session() as session:
        turn = await session.get(TurnRow, turn_id)
        if turn is None or turn.status != "waiting":
            return False
        # A cancelled turn keeps none of its memory writes, and staged pinned
        # rows would keep counting against the bot's pinned budget.
        await MemoryStore().rollback(turn_id)
        turn.status = "cancelled"
        turn.finished_at = finished_at
        # The run that asked has finished, so its stored usage is complete.
        turn.model_messages = None
        for job_id in turn.job_ids:
            await finish_job(session, job_id, "cancelled", finished_at)
        await set_agent(session, turn.agent_id, "idle", finished_at)
        await drop_locks(session, turn.agent_id)
        events: list[Event] = [
            turn_event("turn.finished", turn.id, turn.agent_id, "cancelled"),
        ]
        events.extend(
            job_event("job.done", job_id, turn.agent_id, "cancelled") for job_id in turn.job_ids
        )
        events.append(agent_event(turn.agent_id, "idle"))
        events.extend(await resolve_open_pendings(session, turn, finished_at))
        for event in events:
            session.add(event)
        await session.commit()
        for event in events:
            await hub.relay(event)
    return True


async def _sync_agent_status(
    session: AsyncSession,
    agent_id: str,
    failed_turn_id: str | None,
    now: datetime,
) -> str | None:
    """Match the agent to any turn still open. Return the status when it changes."""
    await session.flush()
    stmt = (
        select(TurnRow.status)
        .where(TurnRow.agent_id == agent_id)
        .where(TurnRow.status.in_(("running", "waiting")))
    )
    if failed_turn_id is not None:
        stmt = stmt.where(TurnRow.id != failed_turn_id)
    open_status = set(await session.scalars(stmt))
    if "running" in open_status:
        desired = "running"
    elif "waiting" in open_status:
        desired = "waiting"
    else:
        desired = "idle"
    agent = await session.get(AgentRow, agent_id)
    if agent is None or agent.status == desired:
        return None
    agent.status = desired
    agent.last_activity_at = now
    return desired
