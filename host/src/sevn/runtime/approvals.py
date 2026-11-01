"""Approval and question policy for a turn: auto-approval, pending rows, question messages."""

from __future__ import annotations

from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.domain.agents import AgentRecord
from sevn.domain.bots import BotRecord
from sevn.domain.ids import new_id
from sevn.runtime.events import ApprovalCall
from sevn.runtime.turn_store import (
    text_parts,
)
from sevn.sandbox.policy import allow_all_enabled
from sevn.sandbox.risk import risk_of
from sevn.store.db import utcnow
from sevn.store.models import Message
from sevn.store.models import PendingRequest as PendingRow


def auto_low(bot: BotRecord, call: ApprovalCall) -> bool:
    """A low-risk shell call under ``auto`` needs no card (D15)."""
    if bot.approval_policy != "auto" or bot.access != "full" or allow_all_enabled():
        return False
    if call.name != "shell":
        return False
    command = call.args.get("command")
    return isinstance(command, str) and risk_of(command) == "low"


def pending_row(turn_id: str, agent_id: str, call: ApprovalCall) -> PendingRow:
    payload: dict[str, object] = {"name": call.name, "args": call.args}
    return PendingRow(
        id=new_id("pend_"),
        turn_id=turn_id,
        agent_id=agent_id,
        kind="approval",
        tool_call_id=call.tool_call_id,
        payload=payload,
        answer=None,
        status="waiting",
        created_at=utcnow(),
        resolved_at=None,
    )


async def question_message(
    session: AsyncSession,
    turn_id: str,
    agent: AgentRecord,
    bot: BotRecord,
    text: str,
) -> Message | None:
    """The assistant message that shows ``user.ask`` questions in the thread.

    A question turn never resumes: the answer arrives as the next user message
    and closes it. Without this message the question lives only in a pending
    row, so a reloaded chat shows a waiting lane with nothing to answer.
    """
    rows = list(
        await session.scalars(
            select(PendingRow)
            .where(PendingRow.turn_id == turn_id)
            .where(PendingRow.kind == "question")
            .where(PendingRow.status == "waiting")
            .order_by(PendingRow.created_at, PendingRow.id)
        )
    )
    if not rows:
        return None
    parts: list[object] = text_parts(text) if text != "" else []
    for row in rows:
        question = _question_text(row.payload)
        parts.append({"type": "text", "text": question})
        parts.append({"type": "question", "pending_id": row.id, "text": question})
    return Message(
        id=new_id("msg_"),
        thread_id=agent.thread_id,
        turn_id=turn_id,
        agent_id=agent.id,
        role="assistant",
        author=bot.id,
        parts=parts,
        created_at=utcnow(),
    )


def _question_text(payload: dict[str, object]) -> str:
    text = payload.get("text")
    if isinstance(text, str):
        return text
    args = payload.get("args")
    if isinstance(args, dict):
        question = cast("dict[str, object]", args).get("question")
        if isinstance(question, str):
            return question
    return ""
