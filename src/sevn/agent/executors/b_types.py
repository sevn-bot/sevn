"""Tier-B executor shared types (`specs/14-executor-tier-b.md` §2-§3).

Module: sevn.agent.executors.b_types
Depends: pydantic, sevn.agent.providers.budget, sevn.tools.base

Exports:
    SessionHandle — minimal session identity for executor calls.
    ChannelPayload — user-visible outbound line(s).
    EscalationRequest — structured B → C/D handoff hint.
    BTurnOutcome — terminal disposition from ``run_b_turn``.
    ResolvedTierBModel — model + transport bundle for tier B.
    SteerInject — gateway ``/steer`` buffer façade.
    BTierDeps — pydantic-ai per-run dependency bag.

Examples:
    >>> BTurnOutcome(
    ...     status="completed",
    ...     final_messages=(ChannelPayload(text="Hello"),),
    ...     escalation=None,
    ...     rounds_used=1,
    ... ).status
    'completed'
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sevn.agent.providers.budget import ModelBudget

if TYPE_CHECKING:
    from sevn.agent.adapters.tool_part_filter import MutableToolAllowlist
from sevn.agent.providers.transport import Transport
from sevn.prompts.fallbacks import (  # re-exported for backward compatibility
    TIER_B_ROUND_BUDGET_NO_ESCALATION_TEMPLATE,
    TIER_B_ROUND_BUDGET_STOP_TEMPLATE,
    TIER_B_ROUND_BUDGET_TEMPLATE,
    TIER_B_SELF_ESCALATION_TEMPLATE,
)
from sevn.tools.base import ToolExecutor
from sevn.tools.context import ToolContext


@dataclass(frozen=True)
class SessionHandle:
    """Gateway session identity passed into tier-B runs."""

    session_id: str


@dataclass(frozen=True)
class ChannelPayload:
    """One user-visible outbound message (channel adapters map later)."""

    text: str
    kind: Literal["text"] = "text"


@dataclass(frozen=True)
class EscalationRequest:
    """Structured escalation emitted by ``request_escalation`` or round-cap policy."""

    reason: str
    target_tier: Literal["C", "D"]
    user_visible_message: str
    original_tools: tuple[str, ...] = field(default_factory=tuple)
    """Tool names the tier-B triager originally requested; union-merged into the C/D re-triage
    result so the originally-intended tool (e.g. ``serp``) survives the B→C escalation
    re-diagnosis that would otherwise drop it.
    """


type BTurnStatus = Literal["completed", "escalated", "cancelled", "failed"]

EXECUTOR_TIMEOUT_CANCEL_DETAIL = "executor_timeout_cancel"
"""``BTurnOutcome.failure_detail`` when ``asyncio.wait_for`` cancels ``run_b_turn``."""


@dataclass(frozen=True)
class BTurnOutcome:
    """Terminal disposition for one tier-B turn (`specs/14-executor-tier-b.md` §2.1)."""

    status: BTurnStatus
    final_messages: tuple[ChannelPayload, ...]
    escalation: EscalationRequest | None
    rounds_used: int
    failure_detail: str | None = None
    had_tool_failures: bool = False
    last_tool_failure_name: str | None = None
    successful_tools_called: frozenset[str] = field(default_factory=frozenset)
    tools_attempted: frozenset[str] = field(default_factory=frozenset)
    codemode_bound_tools_called: frozenset[str] = field(default_factory=frozenset)
    grounding_tools_called: frozenset[str] = field(default_factory=frozenset)
    provider_turn_messages: tuple[dict[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ResolvedTierBModel:
    """Gateway-resolved routing bundle for tier B (`specs/14-executor-tier-b.md` §2.1)."""

    model_id: str
    transport: Transport
    budget: ModelBudget


@dataclass
class SteerInject:
    """Buffered owner ``/steer`` text injected only at LLM boundaries (`specs/14-executor-tier-b.md` §4.5)."""

    pending_text: str | None = None

    def pop_pending(self) -> str | None:
        """Remove and return buffered steer text once.

        Returns:
            str | None: Buffered steer text, or ``None`` if nothing pending.

        Examples:
            >>> SteerInject(pending_text="hi").pop_pending()
            'hi'
            >>> SteerInject().pop_pending() is None
            True
        """

        current = self.pending_text
        self.pending_text = None
        return current

    def inject_pending(self, text: str) -> None:
        """Queue one programmatic steer line for the next LLM-boundary pop.

        Args:
            text (str): Steer payload (ignored when blank after strip).

        Examples:
            >>> steer = SteerInject()
            >>> steer.inject_pending("call `serp` now")
            >>> steer.pop_pending()
            'call `serp` now'
        """
        chunk = text.strip()
        if chunk:
            self.pending_text = chunk


@dataclass
class BTierDeps:
    """Per-run bag wired into pydantic-ai ``RunContext.deps`` (`specs/14-executor-tier-b.md`)."""

    tool_executor: ToolExecutor
    tool_context_template: ToolContext
    workspace_path: Path
    registry_version: int
    loaded_tools: set[str] = field(default_factory=set)
    loaded_skills: set[str] = field(default_factory=set)
    meta_tool_names: frozenset[str] = field(default_factory=frozenset)
    escalation: EscalationRequest | None = None
    channel_payloads: list[ChannelPayload] = field(default_factory=list)
    last_tool_failure_name: str | None = None
    last_tool_failure_detail: str | None = None
    tool_failure_count: int = 0
    tool_failure_by_name: dict[str, int] = field(default_factory=dict)
    successful_tools_called: set[str] = field(default_factory=set)
    successful_skills_called: set[str] = field(default_factory=set)
    codemode_bound_tools_called: set[str] = field(default_factory=set)
    triager_bound_tools: frozenset[str] = field(default_factory=frozenset)
    triager_bound_skills: frozenset[str] = field(default_factory=frozenset)
    grounding_tools_called: set[str] = field(default_factory=set)
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    successful_call_sigs: set[str] = field(default_factory=set)
    steer_buffer: SteerInject | None = None
    tool_allowlist: MutableToolAllowlist | None = None
    fetch_round_steer_injected: bool = False
    """Set after W5/D9 summarize steer fires once mid-turn (post-round-4 fetch loop)."""

    @staticmethod
    def call_signature(tool_name: str, payload: dict[str, Any]) -> str:
        """Return the stable per-turn signature for a tool name + args.

        Args:
            tool_name (str): Registry tool name being dispatched.
            payload (dict[str, Any]): Validated tool arguments.

        Returns:
            str: ``"{name}:{canonical_json_args}"`` signature.

        Examples:
            >>> BTierDeps.call_signature("read", {"path": "a"})
            'read:{"path": "a"}'
        """
        return f"{tool_name}:{json.dumps(payload, sort_keys=True, default=str)}"

    def note_tool_call(self, tool_name: str, payload: dict[str, Any]) -> int:
        """Increment and return the repeat count for a tool name + args signature.

        Args:
            tool_name (str): Registry tool name being dispatched.
            payload (dict[str, Any]): Validated tool arguments.

        Returns:
            int: How many times this exact call signature has been attempted this turn.

        Examples:
            >>> deps = BTierDeps(
            ...     tool_executor=None,  # type: ignore[arg-type]
            ...     tool_context_template=None,  # type: ignore[arg-type]
            ...     workspace_path=__import__("pathlib").Path("/tmp"),
            ...     registry_version=1,
            ... )
            >>> deps.note_tool_call("run_skill_runnable", {"skill": "serp"})
            1
            >>> deps.note_tool_call("run_skill_runnable", {"skill": "serp"})
            2
        """
        sig = self.call_signature(tool_name, payload)
        count = self.tool_call_counts.get(sig, 0) + 1
        self.tool_call_counts[sig] = count
        return count

    def seen_successful_call(self, tool_name: str, payload: dict[str, Any]) -> bool:
        """Whether an identical call already returned ``ok=true`` this turn.

        Args:
            tool_name (str): Registry tool name being dispatched.
            payload (dict[str, Any]): Validated tool arguments.

        Returns:
            bool: True when the exact signature is in ``successful_call_sigs``.

        Examples:
            >>> deps = BTierDeps(
            ...     tool_executor=None,  # type: ignore[arg-type]
            ...     tool_context_template=None,  # type: ignore[arg-type]
            ...     workspace_path=__import__("pathlib").Path("/tmp"),
            ...     registry_version=1,
            ... )
            >>> deps.seen_successful_call("read", {"path": "a"})
            False
            >>> deps.successful_call_sigs.add(deps.call_signature("read", {"path": "a"}))
            >>> deps.seen_successful_call("read", {"path": "a"})
            True
        """
        return self.call_signature(tool_name, payload) in self.successful_call_sigs

    def note_tool_failure(self, tool_name: str, detail: str) -> None:
        """Record the most recent ``ok=false`` tool result for operator reporting.

        Args:
            tool_name (str): Registry tool name that failed.
            detail (str): Error message from the tool envelope.

        Examples:
            >>> deps = BTierDeps(
            ...     tool_executor=None,  # type: ignore[arg-type]
            ...     tool_context_template=None,  # type: ignore[arg-type]
            ...     workspace_path=__import__("pathlib").Path("/tmp"),
            ...     registry_version=1,
            ... )
            >>> deps.note_tool_failure("history", "timeout")
            >>> deps.last_tool_failure_name
            'history'
            >>> deps.tool_failure_count
            1
        """
        self.last_tool_failure_name = tool_name
        self.last_tool_failure_detail = detail
        self.tool_failure_count += 1
        self.tool_failure_by_name[tool_name] = self.tool_failure_by_name.get(tool_name, 0) + 1

    def effective_tool_context(self) -> ToolContext:
        """Clone the template context for per-call dispatch (turn/workspace fields preserved).

        Returns:
            ToolContext: Fresh per-dispatch context cloned from the template.

        Examples:
            >>> import inspect
            >>> "tool_context_template" in inspect.signature(BTierDeps).parameters
            True
        """

        return replace(
            self.tool_context_template,
            outbound_metadata=dict(self.tool_context_template.outbound_metadata),
        )


__all__ = [
    "EXECUTOR_TIMEOUT_CANCEL_DETAIL",
    "TIER_B_ROUND_BUDGET_NO_ESCALATION_TEMPLATE",
    "TIER_B_ROUND_BUDGET_STOP_TEMPLATE",
    "TIER_B_ROUND_BUDGET_TEMPLATE",
    "TIER_B_SELF_ESCALATION_TEMPLATE",
    "BTierDeps",
    "BTurnOutcome",
    "BTurnStatus",
    "ChannelPayload",
    "EscalationRequest",
    "ResolvedTierBModel",
    "SessionHandle",
    "SteerInject",
]
