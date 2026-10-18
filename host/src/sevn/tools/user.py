"""``user.ask`` pauses the turn until the user answers (D12)."""

from __future__ import annotations

from sevn.domain.agents import apply_lifecycle
from sevn.domain.errors import DomainError
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import PendingRequest
from sevn.store.models import Turn as TurnRow
from sevn.tools.registry import TurnDeps, register_toolset


async def ask(agent_id: str, turn_id: str, question: str) -> str:
    """Record a question and leave the turn waiting. Returns the pending id."""
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
                payload={"text": question},
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


def user_toolset(deps: TurnDeps) -> dict[str, object]:
    """The question tool for one turn."""

    async def ask_user(question: str) -> str:
        """Ask the user a question. The turn waits for the answer."""
        return await ask(deps.agent_id, deps.turn_id, question)

    return {"user.ask": ask_user}


register_toolset("user", user_toolset, {"user.ask"})
