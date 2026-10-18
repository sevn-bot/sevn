"""Decision points from spec §7 and the D4 fallback chain."""

from __future__ import annotations

from sevn.config import Settings
from sevn.decisions.base import Attempt, RouteDecision, attempt_for, redact_text
from sevn.decisions.cli_oneshot import CliOneShotDecider
from sevn.decisions.default import DefaultDecider
from sevn.decisions.jev import JevDecider
from sevn.decisions.llm import LLMDecider
from sevn.decisions.log import record_attempt
from sevn.decisions.ollama import OllamaDecider
from sevn.decisions.rules import RuleDecider
from sevn.domain.routing import RoutedMessage, RouterContext

DECISION_POINTS: tuple[str, ...] = (
    "message.intent",
    "message.target_agent",
    "busy.policy",
    "route.owner",
    "delegate.needed",
    "routine.silent",
    "memory.capture",
    "inbound.injection",
    "approval.risk",
    "notify.priority",
)
_PER_AGENT = 2000


def decision_points() -> tuple[str, ...]:
    """Every decision point in spec §7, in table order."""
    return DECISION_POINTS


def router_state(message: RoutedMessage, context: RouterContext) -> str:
    """New message plus the last three user lines of each open agent, redacted."""
    parts = [redact_text(message.text)]
    for agent in context.open_agents:
        recent = context.recent_user_messages.get(agent.id, [])
        block = "\n".join(redact_text(item) for item in recent[-3:])
        if block != "":
            parts.append(block[:_PER_AGENT])
    return "\n".join(parts)


async def decide(message: RoutedMessage, context: RouterContext) -> RouteDecision:
    """Rules, then jev, then the fallback chain. ``provider=rules`` stops after rules."""
    settings = Settings.load().decisions
    state = router_state(message, context)
    # An empty lane list is a rule when asked directly. The chain still asks jev
    # and the fallbacks, and the default step starts a task if they do not.
    ruled = await RuleDecider().decide(message, context, empty_is_new=False)
    if ruled is not None:
        await record_attempt(state, attempt_for(ruled))
        return ruled
    if settings.provider == "rules":
        return RouteDecision(
            intent="new_request",
            target_agent_id=None,
            confidence=0.0,
            path="rule",
        )
    if settings.provider != "llm":
        chosen = await _keep(state, await JevDecider().attempt(context, state))
        if chosen is not None:
            return chosen
    chosen = await _keep(state, await LLMDecider().attempt(state))
    if chosen is not None:
        return chosen
    chosen = await _keep(state, await OllamaDecider().attempt(state))
    if chosen is not None:
        return chosen
    chosen = await _keep(state, await CliOneShotDecider().attempt(context, state))
    if chosen is not None:
        return chosen
    fallback = DefaultDecider().decide(context)
    await record_attempt(state, attempt_for(fallback))
    return fallback


async def _keep(state: str, attempt: Attempt | None) -> RouteDecision | None:
    if attempt is None:
        return None
    await record_attempt(state, attempt)
    if attempt.accepted:
        return attempt.decision
    return None
