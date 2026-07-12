"""Dashboard turn-replay WebSocket fan-out tests (`specs/24-dashboard.md` §2.3)."""

from __future__ import annotations

import asyncio
from typing import Any

from sevn.gateway.replay_job_events import ReplayJobEventFanout, replay_ws_topic


class _RecordingHub:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        self.events.append((topic, payload))


def test_replay_fanout_publishes_ws_topic() -> None:
    hub = _RecordingHub()
    fanout = ReplayJobEventFanout(hub=hub)
    asyncio.run(
        fanout.publish(
            {
                "replay_job_id": "job-ws-1",
                "session_id": "s1",
                "turn_id": "t1",
                "event": "terminal",
                "status": "completed",
            },
        ),
    )
    assert hub.events == [
        (
            replay_ws_topic("job-ws-1"),
            {
                "replay_job_id": "job-ws-1",
                "session_id": "s1",
                "turn_id": "t1",
                "event": "terminal",
                "status": "completed",
            },
        ),
    ]


def test_replay_fanout_noops_without_hub() -> None:
    fanout = ReplayJobEventFanout(hub=None)
    asyncio.run(
        fanout.publish(
            {
                "replay_job_id": "job-ws-2",
                "session_id": "s1",
                "turn_id": "t1",
                "event": "transition",
                "status": "running",
            },
        ),
    )
