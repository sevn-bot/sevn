"""Deterministic last step: one open agent, a new task, or ask the user (D4)."""

from __future__ import annotations

from sevn.decisions.base import RouteDecision
from sevn.domain.routing import RouterContext


class DefaultDecider:
    """Exactly one open agent continues it. None starts a task. Otherwise ask."""

    def decide(self, context: RouterContext) -> RouteDecision:
        agents = list(context.open_agents)
        if len(agents) == 1:
            return RouteDecision(
                intent="follow_up",
                target_agent_id=agents[0].id,
                confidence=1.0,
                path="default",
            )
        if len(agents) == 0:
            return RouteDecision(
                intent="new_request",
                target_agent_id=None,
                confidence=1.0,
                path="default",
            )
        choices = ("New task", *(f"Continue: {agent.title}" for agent in agents))
        return RouteDecision(
            intent="new_request",
            target_agent_id=None,
            confidence=1.0,
            path="user",
            ask_user=True,
            choices=choices,
        )
