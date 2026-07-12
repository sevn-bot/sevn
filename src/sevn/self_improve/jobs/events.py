"""Improve-job event envelopes for dashboard WebSocket fan-out (`specs/33-self-improvement.md` §7).

Module: sevn.self_improve.jobs.events
Depends: typing

Exports:
    ImproveJobEventPayload — serialisable transition payload.
    ImproveJobEventFanoutFn — optional gateway fan-out callback protocol.
    maybe_publish_job_event — invoke fan-out when configured.
    improve_job_ws_topic — ``self_improve.job.{id}`` topic naming per **24** §2.3.
"""

from __future__ import annotations

from typing import Literal, Protocol, TypedDict

ImproveJobState = Literal[
    "queued",
    "running",
    "blocked",
    "awaiting_plan_review",
    "awaiting_eval",
    "awaiting_review",
    "merged",
    "aborted",
]


class ImproveJobEventPayload(TypedDict, total=False):
    """Payload published on ``self_improve.job.{id}`` dashboard topics."""

    job_id: str
    state: ImproveJobState
    event: str
    preset: str
    correlation_id: str | None
    blocked_reason: str | None
    pr_url: str | None
    shortlist_count: int | None


class ImproveJobEventFanoutFn(Protocol):
    """Optional callback for ``self_improve.job.*`` dashboard/Telegram fan-out."""

    async def publish(self, payload: ImproveJobEventPayload) -> None:
        """Publish one improve-job lifecycle event.

        Args:
            payload (ImproveJobEventPayload): Event body for dashboard/Telegram fan-out.

        Returns:
            None: Always.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ImproveJobEventFanoutFn.publish)
            True
        """


async def maybe_publish_job_event(
    fanout: ImproveJobEventFanoutFn | None,
    *,
    payload: ImproveJobEventPayload,
) -> None:
    """Invoke ``fanout.publish`` when a gateway fan-out hook is configured.

    Args:
        fanout (ImproveJobEventFanoutFn | None): Optional publisher.
        payload (ImproveJobEventPayload): Event to emit.

    Returns:
        None: Always.

    Examples:
        >>> import asyncio
        >>> payload: ImproveJobEventPayload = {
        ...     "job_id": "j",
        ...     "state": "queued",
        ...     "event": "transition",
        ...     "preset": "A",
        ... }
        >>> asyncio.run(maybe_publish_job_event(None, payload=payload)) is None
        True
    """
    if fanout is None:
        return
    await fanout.publish(payload)


def improve_job_ws_topic(job_id: str) -> str:
    """Return the Mission Control WebSocket topic for one improve job.

    Args:
        job_id (str): Persistent improve-job identifier.

    Returns:
        str: Topic string ``self_improve.job.{job_id}``.

    Examples:
        >>> improve_job_ws_topic("abc123")
        'self_improve.job.abc123'
    """
    return f"self_improve.job.{job_id}"
