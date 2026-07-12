"""Fan dashboard turn-replay job transitions to Mission Control WS.

Module: sevn.gateway.replay_job_events
Depends: asyncio, typing

Exports:
    ReplayJobEventPayload — JSON body for replay job topics.
    ReplayJobEventFanoutFn — callback type accepted by the replay worker.
    replay_ws_topic — WebSocket topic for one replay job id.
    ReplayJobEventFanout — gateway-injected publisher.
"""

from __future__ import annotations

from typing import Any, Protocol, TypedDict


class ReplayJobEventPayload(TypedDict, total=False):
    """WebSocket payload for ``replay.{replay_job_id}`` topics."""

    replay_job_id: str
    session_id: str
    turn_id: str
    event: str
    status: str
    message: str


class _SupportsPublish(Protocol):
    """Minimal Mission Control hub publish surface."""

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Publish one JSON payload to a dashboard topic.

        Args:
            topic (str): WebSocket topic name.
            payload (dict[str, Any]): JSON-serializable event body.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        ...


class ReplayJobEventFanoutFn(Protocol):
    """Callable surface injected into :class:`TurnReplayWorker`."""

    async def __call__(self, payload: ReplayJobEventPayload) -> None:
        """Publish one replay job lifecycle event.

        Args:
            payload (ReplayJobEventPayload): Transition fields from worker/hooks.

        Examples:
            >>> ReplayJobEventFanoutFn.__name__
            'ReplayJobEventFanoutFn'
        """
        ...


def replay_ws_topic(replay_job_id: str) -> str:
    """Return the dashboard WebSocket topic for one replay job.

    Args:
        replay_job_id (str): Stable replay job identifier.

    Returns:
        str: Topic name such as ``replay.<id>``.

    Examples:
        >>> replay_ws_topic("abc")
        'replay.abc'
    """
    return f"replay.{replay_job_id}"


class ReplayJobEventFanout:
    """Publish ``replay.*`` topics to Mission Control dashboard subscribers."""

    def __init__(self, *, hub: _SupportsPublish | None) -> None:
        """Bind the dashboard pub/sub hub for replay job fan-out.

        Args:
            hub (_SupportsPublish | None): Mission Control hub when configured.

        Examples:
            >>> fan = ReplayJobEventFanout(hub=None)
            >>> fan._hub is None
            True
        """
        self._hub = hub

    async def publish(self, payload: ReplayJobEventPayload) -> None:
        """Fan one replay-job event to dashboard subscribers.

        Args:
            payload (ReplayJobEventPayload): Transition fields from worker/hooks.

        Returns:
            None: Side-effect only.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ReplayJobEventFanout.publish)
            True
        """
        if self._hub is None:
            return
        job_id = str(payload.get("replay_job_id", ""))
        if not job_id:
            return
        topic = replay_ws_topic(job_id)
        await self._hub.publish(topic, dict(payload))


__all__ = [
    "ReplayJobEventFanout",
    "ReplayJobEventFanoutFn",
    "ReplayJobEventPayload",
    "replay_ws_topic",
]
