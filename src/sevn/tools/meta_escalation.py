"""Tier-only escalation tool (`specs/14-executor-tier-b.md` §2.4).

Registers ``request_escalation`` for pydantic-ai tier-B runs; other tiers should not
expose this tool.

Module: sevn.tools.meta_escalation
Depends: pydantic_ai, sevn.agent.executors.b_types

Exports:
    request_escalation_pydantic — async body invoked by the pydantic-ai agent.
    request_escalation_pydantic_tool — ``Tool`` binding for ``Agent``.

Examples:
    >>> request_escalation_pydantic_tool().name
    'request_escalation'
"""

from __future__ import annotations

from typing import Literal

from pydantic_ai import RunContext, Tool

from sevn.agent.executors.b_types import (
    TIER_B_SELF_ESCALATION_TEMPLATE,
    BTierDeps,
    ChannelPayload,
    EscalationRequest,
)
from sevn.tools.base import enveloped_success


async def request_escalation_pydantic(
    ctx: RunContext[BTierDeps],
    reason: str,
    target_tier: Literal["C", "D"],
) -> str:
    """Record escalation, surface the PRD user line, and return a JSON envelope.

    Args:
        ctx (RunContext[BTierDeps]): pydantic-ai run context carrying Tier-B
            deps (channel payload sink + escalation slot).
        reason (str): Free-form rationale captured on ``EscalationRequest``.
        target_tier (Literal["C", "D"]): Deeper planner tier requested by the
            Tier-B agent; gateway re-Triages from this hint.

    Returns:
        str: §3.1 JSON success envelope with ``data.escalated`` true and
            ``data.target_tier`` echoed.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(request_escalation_pydantic)
        True
        >>> sorted(inspect.signature(request_escalation_pydantic).parameters)
        ['ctx', 'reason', 'target_tier']
    """
    line = TIER_B_SELF_ESCALATION_TEMPLATE.format(tier=target_tier)
    ctx.deps.channel_payloads.append(ChannelPayload(text=line))
    ctx.deps.escalation = EscalationRequest(
        reason=reason,
        target_tier=target_tier,
        user_visible_message=line,
    )
    return enveloped_success({"escalated": True, "target_tier": target_tier})


def request_escalation_pydantic_tool() -> Tool[BTierDeps]:
    """Build the pydantic-ai registration row.

    Returns:
        Tool[BTierDeps]: pydantic-ai ``Tool`` bound to
            :func:`request_escalation_pydantic` and named ``request_escalation``.

    Examples:
        >>> request_escalation_pydantic_tool().name
        'request_escalation'
    """
    return Tool(
        request_escalation_pydantic,
        name="request_escalation",
        description="Escalate to a deeper planner tier (hint only; gateway re-Triages).",
    )


__all__ = [
    "request_escalation_pydantic",
    "request_escalation_pydantic_tool",
]
