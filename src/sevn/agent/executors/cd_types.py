"""Tier C/D executor types (`specs/21-executor-tier-cd.md` §2-§3).

Module: sevn.agent.executors.cd_types
Depends: dataclasses, pydantic, sevn.agent.executors.b_types, sevn.agent.providers.budget,
    sevn.agent.providers.transport, sevn.agent.tracing.sink

Exports:
    PlanStep — one planned step row.
    Plan — JSON-serialisable plan artefact (§3.2).
    CdTurnOutcome — ``run_cd_turn`` return payload (§2.1).
    ResolvedCdOuterModels — outer/sub LM routing bundle (§2.2).
    PlanGatePort — approval port (§2.3).
    CdDspyPipelinePort — injectable DSPy-shaped phase port (§4.1).

Examples:
    >>> Plan(
    ...     steps=[PlanStep(id="1", title="t")],
    ...     summary="s",
    ...     meta=Plan.Meta(complexity="C", registry_version=1),
    ... ).meta.complexity
    'C'
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from sevn.agent.executors.b_types import ChannelPayload
from sevn.agent.providers.budget import ModelBudget
from sevn.agent.providers.transport import Transport
from sevn.agent.tracing.sink import TraceSink

CdBackendLiteral = Literal["dspy", "lambda_rlm"]
CdTurnStatus = Literal["completed", "cancelled", "failed", "superseded"]


class PlanStep(BaseModel):
    """Single plan step (`specs/21-executor-tier-cd.md` §3.2)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    tool_guess: str | None = None
    requires_human: bool = False


class Plan(BaseModel):
    """Structured plan persisted via PlanGate / ``pending_plans`` (§3.2)."""

    model_config = ConfigDict(extra="forbid")

    class Meta(BaseModel):
        """Plan metadata echoing triage + registry generation."""

        model_config = ConfigDict(extra="forbid")

        complexity: Literal["C", "D"]
        registry_version: int = Field(ge=0)

    steps: list[PlanStep] = Field(default_factory=list, min_length=1)
    summary: str
    meta: Meta


@runtime_checkable
class PlanGatePort(Protocol):
    """Abstract approval surface (SQLite + Telegram owned elsewhere; §2.3)."""

    async def await_approval(
        self,
        *,
        plan: Plan,
        session_id: str,
        turn_id: str,
        trace: TraceSink | None,
    ) -> Literal["approved", "superseded"] | Plan:
        """Block for owner decision or return terminal gate labels.

        Args:
            plan (Plan): Pending plan artefact.
            session_id (str): Gateway session id.
            turn_id (str): Correlation id for tracing.
            trace (TraceSink | None): Optional trace sink.

        Returns:
            Literal["approved", "superseded"] | Plan: Gate outcome or edited plan.

        Examples:
            >>> import asyncio
            >>> from sevn.agent.executors.cd_types import Plan, PlanGatePort, PlanStep
            >>> class Gate:
            ...     async def await_approval(self, *, plan, session_id, turn_id, trace):
            ...         return "approved"
            >>> isinstance(Gate(), PlanGatePort)
            True
            >>> p = Plan(
            ...     steps=[PlanStep(id="1", title="t")],
            ...     summary="s",
            ...     meta=Plan.Meta(complexity="C", registry_version=1),
            ... )
            >>> asyncio.run(Gate().await_approval(
            ...     plan=p, session_id="s", turn_id="t", trace=None))
            'approved'
        """
        ...


@runtime_checkable
class CdDspyPipelinePort(Protocol):
    """Injectable DSPy-shaped phases for tests / future built-in wiring (`specs/21-executor-tier-cd.md` §4.1)."""

    async def decompose(self, task: str) -> Plan:
        """Return a structured plan (``DecomposeSig`` analogue).

        Args:
            task (str): User task text.

        Returns:
            Plan: Parsed plan rows.

        Examples:
            >>> import asyncio
            >>> from sevn.agent.executors.cd_types import Plan, PlanStep
            >>> class Pipe:
            ...     async def decompose(self, task: str):
            ...         return Plan(
            ...             steps=[PlanStep(id="1", title="a")],
            ...             summary=task,
            ...             meta=Plan.Meta(complexity="C", registry_version=1),
            ...         )
            ...     async def run_outer_rlm(self, plan, task):
            ...         return ("x", 0, False)
            ...     async def synthesize(self, task, execution_summary):
            ...         return "y"
            >>> asyncio.run(Pipe().decompose("hi")).summary
            'hi'
        """
        ...

    async def run_outer_rlm(self, plan: Plan, task: str) -> tuple[str, int, bool]:
        """Execute one outer RLM unit; returns (summary, inner_llm_calls, inner_exhausted).

        Args:
            plan (Plan): Working plan from decompose or gate.
            task (str): User-visible task text.

        Returns:
            tuple[str, int, bool]: Summary text, inner LLM call count, inner exhausted flag.

        Examples:
            >>> import asyncio
            >>> from sevn.agent.executors.cd_types import Plan, PlanStep
            >>> class Pipe:
            ...     async def decompose(self, task: str):
            ...         return Plan(
            ...             steps=[PlanStep(id="1", title="a")],
            ...             summary=task,
            ...             meta=Plan.Meta(complexity="C", registry_version=1),
            ...         )
            ...     async def run_outer_rlm(self, plan, task):
            ...         return ("out", 2, True)
            ...     async def synthesize(self, task, execution_summary):
            ...         return "y"
            >>> p = asyncio.run(Pipe().decompose("t"))
            >>> asyncio.run(Pipe().run_outer_rlm(p, "t"))[1]
            2
        """
        ...

    async def synthesize(self, task: str, execution_summary: str) -> str:
        """Produce closing user text (``SynthSig`` analogue).

        Args:
            task (str): Original user task.
            execution_summary (str): Aggregated execution blob.

        Returns:
            str: Final user-visible reply.

        Examples:
            >>> import asyncio
            >>> from sevn.agent.executors.cd_types import Plan, PlanStep
            >>> class Pipe:
            ...     async def decompose(self, task: str):
            ...         return Plan(
            ...             steps=[PlanStep(id="1", title="a")],
            ...             summary=task,
            ...             meta=Plan.Meta(complexity="C", registry_version=1),
            ...         )
            ...     async def run_outer_rlm(self, plan, task):
            ...         return ("x", 0, False)
            ...     async def synthesize(self, task, execution_summary):
            ...         return task + ":" + execution_summary
            >>> asyncio.run(Pipe().synthesize("a", "b"))
            'a:b'
        """
        ...


@dataclass(frozen=True)
class ResolvedCdOuterModels:
    """Gateway-resolved transports for C/D outer + optional inner sub-LM (§2.2)."""

    outer_model_id: str
    outer_transport: Transport
    outer_budget: ModelBudget
    sub_lm_model_id: str | None
    sub_lm_transport: Transport | None
    sub_lm_budget: ModelBudget | None


@dataclass(frozen=True)
class CdTurnOutcome:
    """Terminal disposition for one C/D turn (`specs/21-executor-tier-cd.md` §2.1)."""

    status: CdTurnStatus
    final_messages: tuple[ChannelPayload, ...]
    c_d_backend: CdBackendLiteral
    rounds_outer_used: int
    rounds_inner_exhausted: bool
    failure_detail: str | None = None


__all__ = [
    "CdBackendLiteral",
    "CdDspyPipelinePort",
    "CdTurnOutcome",
    "CdTurnStatus",
    "Plan",
    "PlanGatePort",
    "PlanStep",
    "ResolvedCdOuterModels",
]
