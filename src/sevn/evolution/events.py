"""Evolution issue event envelopes for dashboard WebSocket fan-out (`specs/35-bot-evolution.md` §2.8).

Module: sevn.evolution.events
Depends: typing

Exports:
    EvolutionIssueEventPayload — serialisable pipeline transition payload.
    EvolutionIssueEventFanoutFn — optional gateway fan-out callback protocol.
    maybe_publish_issue_event — invoke fan-out when configured.
    evolution_issue_ws_topic — ``evolution.issue.{id}`` topic naming per **24** §2.3.
"""

from __future__ import annotations

from typing import Literal, Protocol, TypedDict

EvolutionIssueEventKind = Literal["transition", "log_line", "approval"]


class EvolutionIssueEventPayload(TypedDict, total=False):
    """Payload published on ``evolution.issue.{id}`` dashboard topics."""

    issue_id: str
    event: EvolutionIssueEventKind
    state: str
    pipeline_stage: str | None
    line: str
    approval_id: str | None
    pr_url: str


class EvolutionIssueEventFanoutFn(Protocol):
    """Optional callback for ``evolution.issue.*`` dashboard/Telegram fan-out."""

    async def publish(self, payload: EvolutionIssueEventPayload) -> None:
        """Publish one evolution issue lifecycle event.

        Args:
            payload (EvolutionIssueEventPayload): Event body for dashboard/Telegram fan-out.

        Returns:
            None: Always.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(EvolutionIssueEventFanoutFn.publish)
            True
        """


async def maybe_publish_issue_event(
    fanout: EvolutionIssueEventFanoutFn | None,
    *,
    payload: EvolutionIssueEventPayload,
) -> None:
    """Invoke ``fanout.publish`` when a gateway fan-out hook is configured.

    Args:
        fanout (EvolutionIssueEventFanoutFn | None): Optional publisher.
        payload (EvolutionIssueEventPayload): Event to emit.

    Returns:
        None: Always.

    Examples:
        >>> import asyncio
        >>> payload: EvolutionIssueEventPayload = {
        ...     "issue_id": "i1",
        ...     "event": "transition",
        ...     "state": "implementing",
        ... }
        >>> asyncio.run(maybe_publish_issue_event(None, payload=payload)) is None
        True
    """
    if fanout is None:
        return
    await fanout.publish(payload)


def evolution_issue_ws_topic(issue_id: str) -> str:
    """Return the Mission Control WebSocket topic for one evolution issue pipeline.

    Args:
        issue_id (str): Persisted evolution issue identifier.

    Returns:
        str: Topic string ``evolution.issue.{issue_id}``.

    Examples:
        >>> evolution_issue_ws_topic("abc123")
        'evolution.issue.abc123'
    """
    return f"evolution.issue.{issue_id}"


__all__ = [
    "EvolutionIssueEventFanoutFn",
    "EvolutionIssueEventKind",
    "EvolutionIssueEventPayload",
    "evolution_issue_ws_topic",
    "maybe_publish_issue_event",
]
