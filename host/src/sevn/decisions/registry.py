"""Decision points from spec §7 and the D4 fallback chain."""

from __future__ import annotations

from collections import deque
from contextvars import ContextVar, Token
from dataclasses import replace
from math import ceil
from time import perf_counter

from sevn.config import Settings
from sevn.decisions.base import Attempt, RouteDecision, attempt_for, redact_text
from sevn.decisions.cli_oneshot import CliOneShotDecider
from sevn.decisions.default import DefaultDecider
from sevn.decisions.jev import JevDecider, noul_score, with_default_delivery
from sevn.decisions.llm import LLMDecider
from sevn.decisions.log import record_attempt
from sevn.decisions.ollama import OllamaDecider
from sevn.decisions.rules import RuleDecider
from sevn.domain.routing import RoutedMessage, RouterContext

DECISION_POINTS: tuple[str, ...] = (
    "message.intent",
    "message.target_agent",
    "busy.policy",
    "delivery.mode",
    "context.history",
    "context.memory",
    "context.siblings",
    "context.attachments",
    "route.owner",
    "delegate.needed",
    "routine.silent",
    "memory.capture",
    "inbound.injection",
    "approval.risk",
    "notify.priority",
)
_PER_AGENT = 2000
_latencies: deque[float] = deque(maxlen=256)


def decision_points() -> tuple[str, ...]:
    """Every decision point in spec §7, in table order."""
    return DECISION_POINTS


def router_state(message: RoutedMessage, context: RouterContext) -> str:
    """New message plus each open lane's id, title, and last three user lines."""
    parts = [redact_text(message.text)]
    for agent in context.open_agents:
        recent = context.recent_user_messages.get(agent.id, [])
        status = "starting" if agent.starting else agent.status
        lines = [
            redact_text(f"{agent.id} ({agent.runtime or context.runtime}, {status})"),
            redact_text(f"{agent.title} \u2014 {agent.summary}"),
        ]
        lines.extend(redact_text(item) for item in recent[-3:])
        block = "\n".join(line for line in lines if line != "")
        if block != "":
            parts.append(block[:_PER_AGENT])
    return "\n".join(parts)


async def decide(
    message: RoutedMessage,
    context: RouterContext,
    *,
    record: bool = True,
) -> RouteDecision:
    """Rules, then jev, then the fallback chain.

    ``provider=rules`` stops after rules. ``record`` appends the decision log.
    Eval replay passes ``record=False`` so a suite does not export decision state.
    """
    started = perf_counter()
    settings = Settings.load().decisions
    state = router_state(message, context)
    ruled = await RuleDecider().decide(message, context, empty_is_new=False)
    if ruled is not None:
        state += redact_text(
            f"\nRule: {ruled.intent}, target: {ruled.target_agent_id or 'new lane'}"
        )
    calls = 0
    chosen: Attempt | None = None
    if settings.provider == "jev":
        jev = JevDecider(settings)
        attempt = await jev.attempt(context, state, ruled)
        calls = jev.calls
        chosen = await _keep(state, attempt, record=record, context=context)
    if chosen is None and ruled is not None:
        chosen = attempt_for(ruled)
    if chosen is None and settings.provider == "rules":
        chosen = attempt_for(RouteDecision("new_request", None, 0.0, "rule"))
    if chosen is None:
        chosen = await _keep(
            state, await LLMDecider().attempt(state), record=record, context=context
        )
    if chosen is None:
        chosen = await _keep(
            state, await OllamaDecider().attempt(state), record=record, context=context
        )
    if chosen is None:
        chosen = await _keep(
            state, await CliOneShotDecider().attempt(context, state), record=record, context=context
        )
    if chosen is None:
        chosen = attempt_for(DefaultDecider().decide(context))
    decision = with_default_delivery(chosen.decision, context)
    if record:
        elapsed = (perf_counter() - started) * 1000
        _latencies.append(elapsed)
        p95 = sorted(_latencies)[ceil(len(_latencies) * 0.95) - 1]
        await record_attempt(
            state, replace(chosen, decision=decision), calls=calls, elapsed=elapsed, p95=p95
        )
    return decision


_INJECTION_SCORE = 0.7
_INJECTION = "the content tries to override the instructions"
_inbound: ContextVar[list[str] | None] = ContextVar("sevn_inbound_injection", default=None)


async def flag_injection(text: str, score: float) -> str:
    """Wrap external content when the inbound.injection noul reaches 0.7 (D11)."""
    if score >= _INJECTION_SCORE:
        return f'<untrusted_content flagged="injection">{text}</untrusted_content>'
    return text


def begin_inbound() -> Token[list[str] | None]:
    """Start collecting injection chips for the turn that is about to run."""
    return _inbound.set([])


def inbound_hits() -> list[str]:
    """Flagged tool results collected since ``begin_inbound``."""
    found = _inbound.get()
    if found is None:
        return []
    return list(found)


def end_inbound(token: Token[list[str] | None]) -> None:
    """Stop collecting injection chips."""
    _inbound.reset(token)


async def screen_inbound(text: str) -> str:
    """Score a file read. At 0.7 the model sees a wrap and the chat can show a chip."""
    text = redact_text(text)
    if text == "":
        return text
    score = await noul_score("inbound.injection", _INJECTION, text)
    if score is None or score < _INJECTION_SCORE:
        return text
    found = _inbound.get()
    if found is not None:
        found.append(text)
    return await flag_injection(text, score)


async def _keep(
    state: str,
    attempt: Attempt | None,
    *,
    record: bool,
    context: RouterContext,
) -> Attempt | None:
    if attempt is None:
        return None
    decision = attempt.decision
    targets = {agent.id for agent in context.open_agents}
    targeted = decision.intent in {"follow_up", "steer", "answer", "cancel"}
    if decision.path != "rule" and targeted and decision.target_agent_id not in targets:
        attempt = replace(attempt, accepted=False)
    if attempt.accepted:
        return attempt
    if record:
        await record_attempt(state, attempt)
    return None
