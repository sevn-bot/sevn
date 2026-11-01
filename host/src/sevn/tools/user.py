"""``user.ask`` pauses the turn until the user answers (D12)."""

from __future__ import annotations

from datetime import datetime

from sevn.domain.agents import apply_lifecycle
from sevn.domain.errors import DomainError
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import PendingRequest
from sevn.store.models import Turn as TurnRow
from sevn.tools.registry import TurnDeps, register_toolset

PRIORITIES = ("low", "normal", "high")
MAX_OPTIONS = 6
_LABEL_LIMIT = 120


async def ask(
    agent_id: str,
    turn_id: str,
    question: str,
    *,
    options: list[str] | None = None,
    priority: str = "normal",
    due_by: str | None = None,
    blocking: bool = True,
) -> str:
    """Record a question and leave the turn waiting. Returns the pending id.

    ``options`` become one-click answers with ids ``opt_1``... ``priority`` is
    low, normal or high. ``due_by`` is ISO 8601 with a timezone. ``blocking``
    says whether the work stops until the answer.
    """
    choices = _options(options or [])
    if priority not in PRIORITIES:
        raise DomainError("invalid_params", "priority must be low, normal or high")
    due = _due(due_by)
    pending_id = new_id("pend_")
    now = utcnow()
    async with open_session() as session:
        turn = await session.get(TurnRow, turn_id)
        if turn is None:
            raise DomainError("not_found", "turn not found")
        agent = await session.get(AgentRow, agent_id)
        if agent is None:
            raise DomainError("not_found", "agent not found")
        session.add(
            PendingRequest(
                id=pending_id,
                turn_id=turn_id,
                agent_id=agent_id,
                kind="question",
                tool_call_id=None,
                payload={
                    "text": question,
                    "name": "user.ask",
                    "args": {"question": question},
                    "options": choices,
                    "priority": priority,
                    "due_by": due,
                    "blocking": blocking,
                },
                answer=None,
                status="waiting",
                created_at=now,
                resolved_at=None,
            )
        )
        turn.status = "waiting"
        agent.status = "waiting"
        agent.last_activity_at = now
        apply_lifecycle(agent, "waiting", now)
        await session.commit()
    return pending_id


def _options(raw: list[str]) -> list[dict[str, str]]:
    if len(raw) > MAX_OPTIONS:
        raise DomainError("invalid_params", f"at most {MAX_OPTIONS} options")
    choices: list[dict[str, str]] = []
    for index, label in enumerate(raw, start=1):
        cleaned = " ".join(label.split())
        if cleaned == "":
            raise DomainError("invalid_params", "an option is empty")
        choices.append({"id": f"opt_{index}", "label": cleaned[:_LABEL_LIMIT]})
    return choices


def _due(raw: str | None) -> str | None:
    if raw is None or raw == "":
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise DomainError("invalid_params", "due_by must be ISO 8601") from None
    if parsed.tzinfo is None:
        raise DomainError("invalid_params", "due_by needs a timezone offset")
    return parsed.isoformat()


def user_toolset(deps: TurnDeps) -> dict[str, object]:
    """The question tool for one turn."""

    async def ask_user(
        question: str,
        options: list[str] | None = None,
        priority: str = "normal",
        due_by: str | None = None,
        blocking: bool = True,
    ) -> str:
        """Ask the user a question. The turn waits for the answer.

        Give ``options`` when the answer is one of a few choices; the user can
        pick one with a click. ``priority`` is low, normal or high. ``due_by``
        is an ISO 8601 time with a timezone. Set ``blocking`` to false when
        the work does not stop for the answer.
        """
        try:
            return await ask(
                deps.agent_id,
                deps.turn_id,
                question,
                options=options,
                priority=priority,
                due_by=due_by,
                blocking=blocking,
            )
        except DomainError as exc:
            if exc.code != "invalid_params":
                raise
            return f"invalid_params: {exc.message}"

    return {"user.ask": ask_user}


register_toolset("user", user_toolset, {"user.ask"})
