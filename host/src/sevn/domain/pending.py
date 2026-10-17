"""Approval rows for a waiting turn (D8)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from sevn.domain.errors import DomainError
from sevn.domain.session import open_session
from sevn.store.db import utcnow
from sevn.store.models import PendingRequest


class PendingRecord(BaseModel):
    """One request the user still has to answer, or has just answered."""

    model_config = ConfigDict(extra="forbid")

    id: str
    turn_id: str
    agent_id: str
    kind: str
    tool_call_id: str | None
    status: str


class PendingService:
    """List waiting approvals and record one answer."""

    async def list_waiting(self) -> list[PendingRecord]:
        async with open_session() as session:
            rows = list(
                await session.scalars(
                    select(PendingRequest)
                    .where(PendingRequest.status == "waiting")
                    .order_by(PendingRequest.created_at)
                )
            )
            return [_record(row) for row in rows]

    async def resolve(self, pending_id: str, decision: str) -> PendingRecord:
        async with open_session() as session:
            row = await session.get(PendingRequest, pending_id)
            if row is None:
                raise DomainError("not_found", "pending request not found")
            if row.status != "waiting":
                raise DomainError("pending_resolved", "pending request is resolved")
            row.status = "resolved"
            row.answer = {"decision": decision}
            row.resolved_at = utcnow()
            await session.commit()
            return _record(row)

    async def has_waiting(self, turn_id: str) -> bool:
        async with open_session() as session:
            found = await session.scalar(
                select(PendingRequest.id)
                .where(PendingRequest.turn_id == turn_id)
                .where(PendingRequest.status == "waiting")
                .limit(1)
            )
            return found is not None

    async def decisions(self, turn_id: str) -> list[tuple[str, bool]]:
        """Resolved tool calls for ``turn_id``, as ``(tool_call_id, approved)``."""
        async with open_session() as session:
            rows = list(
                await session.scalars(
                    select(PendingRequest).where(PendingRequest.turn_id == turn_id)
                )
            )
        chosen: list[tuple[str, bool]] = []
        for row in rows:
            if row.tool_call_id is None or row.status != "resolved":
                continue
            chosen.append((row.tool_call_id, _approved(row.answer)))
        return chosen


def _approved(answer: dict[str, object] | None) -> bool:
    if answer is None:
        return False
    return answer.get("decision") == "approve"


def _record(row: PendingRequest) -> PendingRecord:
    return PendingRecord(
        id=row.id,
        turn_id=row.turn_id,
        agent_id=row.agent_id,
        kind=row.kind,
        tool_call_id=row.tool_call_id,
        status=row.status,
    )
