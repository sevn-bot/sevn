"""The runtime seam every backend implements (D3, spec A.2.1)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from sevn.domain.agents import AgentRecord
from sevn.domain.bots import BotRecord
from sevn.runtime.events import RuntimeEvent


@dataclass(frozen=True, slots=True)
class SessionRef:
    """Handle returned by ``Runtime.open``."""

    agent_id: str
    session_ref: str | None = None


@dataclass(frozen=True, slots=True)
class PendingAnswer:
    """A user's answer to one pending request."""

    decision: str


@dataclass(frozen=True, slots=True)
class ToolDecision:
    """Whether one deferred tool call may run."""

    tool_call_id: str
    approved: bool


@dataclass(frozen=True, slots=True)
class TurnContext:
    """Inputs for one ``run_turn`` call."""

    agent: AgentRecord
    text: str
    bot: BotRecord | None = None
    job_id: str = ""
    turn_id: str | None = None
    message_history: list[object] | None = None
    approvals: tuple[ToolDecision, ...] | None = None


class Runtime(Protocol):
    """One model backend. ``run_turn`` yields sevn events, not provider types."""

    async def open(self, agent: AgentRecord) -> SessionRef: ...

    def run_turn(self, turn: TurnContext) -> AsyncIterator[RuntimeEvent]: ...

    async def answer(self, pending_id: str, answer: PendingAnswer) -> None: ...

    async def interrupt(self, agent_id: str) -> None: ...

    async def close(self, agent_id: str) -> None: ...
