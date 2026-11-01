"""Sibling agent tools (D12)."""

from __future__ import annotations

from sevn.domain.agents import AgentRecord, AgentService
from sevn.domain.errors import DomainError
from sevn.tools.registry import TurnDeps, register_toolset


async def list_agents(bot_id: str) -> list[AgentRecord]:
    """Every agent of one bot."""
    return await AgentService().list(bot_id)


async def read_agent(agent_id: str) -> AgentRecord:
    """One agent, including title and summary."""
    return await AgentService().get(agent_id)


async def close_agent(agent_id: str) -> AgentRecord:
    """Mark the agent done and release its path locks."""
    return await AgentService().set_status(agent_id, "done")


def agents_toolset(deps: TurnDeps) -> dict[str, object]:
    """Agent tools bound to the caller."""

    async def list_open() -> str:
        """List this bot's agents: id, status, title, summary."""
        rows = await list_agents(deps.bot_id)
        return "\n".join(_line(item) for item in rows)

    async def read_one(agent_id: str) -> str:
        """Read one of this bot's agents: title, status, and summary."""
        try:
            agent = await read_agent(agent_id)
        except DomainError as exc:
            return exc.code
        if agent.bot_id != deps.bot_id:
            return "not_found"
        return _line(agent)

    async def close_self() -> str:
        """Mark this agent done."""
        closed = await close_agent(deps.agent_id)
        return closed.id

    return {
        "agent.list": list_open,
        "agent.read": read_one,
        "agent.close": close_self,
    }


def _line(agent: AgentRecord) -> str:
    title = agent.title if agent.title != "" else agent.id
    return f"{agent.id}\t{agent.status}\t{title}\t{agent.summary}"


register_toolset(
    "agents",
    agents_toolset,
    {"agent.list", "agent.read"},
    deferred={"agent.close"},
)
