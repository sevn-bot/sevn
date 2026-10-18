"""First-match routing rules (D3), then any rules registered for the source."""

from __future__ import annotations

from datetime import timedelta

from sevn.decisions.base import RouteDecision
from sevn.domain.routing import (
    OpenAgent,
    PendingQuestion,
    RoutedMessage,
    RouterContext,
    source_rules,
)

_CONTINUE = "/continue "
_NEW = "/new"
_ANSWER_WINDOW = timedelta(minutes=10)


class RuleDecider:
    """Built-in rules, after source plugins. The first match wins."""

    async def decide(
        self,
        message: RoutedMessage,
        context: RouterContext,
        *,
        empty_is_new: bool = True,
    ) -> RouteDecision | None:
        for rule in source_rules(message.source):
            found = rule(message, context)
            if found is not None:
                return found
        return _builtin(message, context, empty_is_new=empty_is_new)


def _builtin(
    message: RoutedMessage,
    context: RouterContext,
    *,
    empty_is_new: bool,
) -> RouteDecision | None:
    if message.reply_to_agent_id:
        return _follow(message.reply_to_agent_id)
    if message.agent_id:
        return _follow(message.agent_id)
    if message.new_agent or _slash_new(message.text):
        return _new()
    continued = _continue_id(message.text, context.open_agents)
    if continued is not None:
        return _follow(continued)
    if empty_is_new and len(context.open_agents) == 0:
        return _new()
    answered = _pending_target(message, context.pending_questions)
    if answered is not None:
        return RouteDecision(
            intent="answer",
            target_agent_id=answered,
            confidence=1.0,
            path="rule",
        )
    return None


def _follow(agent_id: str) -> RouteDecision:
    return RouteDecision(
        intent="follow_up",
        target_agent_id=agent_id,
        confidence=1.0,
        path="rule",
    )


def _new() -> RouteDecision:
    return RouteDecision(
        intent="new_request",
        target_agent_id=None,
        confidence=1.0,
        path="rule",
    )


def _slash_new(text: str) -> bool:
    if not text.startswith(_NEW):
        return False
    return len(text) == len(_NEW) or text[len(_NEW)] == " "


def _continue_id(text: str, agents: list[OpenAgent]) -> str | None:
    if not text.startswith(_CONTINUE):
        return None
    prefix = text[len(_CONTINUE) :]
    if prefix == "":
        return None
    matches = [agent.id for agent in agents if agent.title.startswith(prefix)]
    if len(matches) != 1:
        return None
    return matches[0]


def _pending_target(message: RoutedMessage, pending: list[PendingQuestion]) -> str | None:
    if message.author != "user" or len(pending) != 1:
        return None
    question = pending[0]
    delta = message.created_at - question.asked_at
    if delta < timedelta(0) or delta > _ANSWER_WINDOW:
        return None
    return question.agent_id
