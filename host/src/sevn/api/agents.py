"""Agent protocol methods (D10)."""

from __future__ import annotations

from sevn.api.errors import raise_protocol
from sevn.contracts.methods import (
    AgentsGetParams,
    AgentsListParams,
    AgentsListResult,
)
from sevn.domain.agents import AgentRecord, AgentService
from sevn.domain.errors import DomainError
from sevn.protocol.registry import Ctx, method


@method("agents.list", params=AgentsListParams, result=AgentsListResult, mutating=False)
async def agents_list(_ctx: Ctx, params: AgentsListParams) -> AgentsListResult:
    try:
        agents = await AgentService().list(params.bot_id)
    except DomainError as exc:
        raise_protocol(exc)
    return AgentsListResult(agents=agents)


@method("agents.get", params=AgentsGetParams, result=AgentRecord, mutating=False)
async def agents_get(_ctx: Ctx, params: AgentsGetParams) -> AgentRecord:
    try:
        return await AgentService().get(params.agent_id)
    except DomainError as exc:
        raise_protocol(exc)
