"""Approval rows for a waiting turn (D8)."""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from sevn.domain.errors import DomainError
from sevn.domain.session import open_session
from sevn.store.db import utcnow
from sevn.store.models import PendingRequest
from sevn.store.models import Turn as TurnRow


class PendingRecord(BaseModel):
    """One request the user still has to answer, or has just answered."""

    model_config = ConfigDict(extra="forbid")

    id: str
    turn_id: str
    agent_id: str
    kind: str
    tool_call_id: str | None
    name: str
    args: dict[str, object]
    status: str


class PendingService:
    """List waiting approvals and record one answer."""

    async def list_waiting(self) -> list[PendingRecord]:
        async with open_session() as session:
            rows = list(
                await session.scalars(
                    select(PendingRequest)
                    .where(PendingRequest.status == "waiting")
                    .where(PendingRequest.kind == "approval")
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

    async def kind_of(self, pending_id: str) -> str:
        """``approval`` or ``question``. ``not_found`` for an unknown id."""
        async with open_session() as session:
            row = await session.get(PendingRequest, pending_id)
            if row is None:
                raise DomainError("not_found", "pending request not found")
            return row.kind

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
        """Resolved calls on the latest model response, as ``(tool_call_id, approved)``.

        Earlier ids on the same turn are already settled. A resume has to name
        exactly the tool calls on the latest response.
        """
        async with open_session() as session:
            turn = await session.get(TurnRow, turn_id)
            rows = list(
                await session.scalars(
                    select(PendingRequest).where(PendingRequest.turn_id == turn_id)
                )
            )
            current = latest_response_tool_call_ids(None if turn is None else turn.model_messages)
        chosen: list[tuple[str, bool]] = []
        for row in rows:
            if row.tool_call_id is None or row.status != "resolved":
                continue
            if current is not None and row.tool_call_id not in current:
                continue
            chosen.append((row.tool_call_id, _approved(row.answer)))
        return chosen


def latest_response_tool_call_ids(messages: object) -> set[str] | None:
    """Tool call ids on the latest model response.

    ``None`` when ``messages`` has no response, so a single saved batch can
    still resume. An empty set means the response carried no tool calls.
    """
    if not isinstance(messages, list):
        return None
    for message in reversed(cast("list[object]", messages)):
        body = _object_dict(message)
        if body is None or body.get("kind") != "response":
            continue
        return _response_tool_call_ids(body.get("parts"))
    return None


def _approved(answer: dict[str, object] | None) -> bool:
    if answer is None:
        return False
    return answer.get("decision") == "approve"


def _object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    mapped: dict[str, object] = {}
    for key, item in cast("dict[object, object]", value).items():
        if isinstance(key, str):
            mapped[key] = item
    return mapped


def _response_tool_call_ids(parts: object) -> set[str]:
    if not isinstance(parts, list):
        return set()
    found: set[str] = set()
    for part in cast("list[object]", parts):
        body = _object_dict(part)
        if body is None or body.get("part_kind") != "tool-call":
            continue
        call_id = body.get("tool_call_id")
        if isinstance(call_id, str) and call_id != "":
            found.add(call_id)
    return found


def _record(row: PendingRequest) -> PendingRecord:
    name, args = _tool_view(row.payload)
    return PendingRecord(
        id=row.id,
        turn_id=row.turn_id,
        agent_id=row.agent_id,
        kind=row.kind,
        tool_call_id=row.tool_call_id,
        name=name,
        args=args,
        status=row.status,
    )


def _tool_view(payload: object) -> tuple[str, dict[str, object]]:
    """Tool name and arguments stored on the pending row."""
    body = _object_dict(payload)
    if body is None:
        return "", {}
    raw_name = body.get("name")
    name = raw_name if isinstance(raw_name, str) else ""
    args = _object_dict(body.get("args"))
    if args is None:
        return name, {}
    return name, args
