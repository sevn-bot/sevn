"""Improve-job dashboard + Telegram fan-out (`specs/24-dashboard.md` §2.3)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.self_improve.self_improve_job_events import SelfImproveJobEventFanout

if TYPE_CHECKING:
    from sevn.gateway.channel_router import OutgoingMessage


class _RecordingHub:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        self.events.append((topic, payload))


class _RecordingTelegram:
    def __init__(self) -> None:
        self.messages: list[OutgoingMessage] = []

    async def send(self, message: OutgoingMessage) -> list[str]:
        self.messages.append(message)
        return ["1"]


def test_fanout_publishes_ws_topic_when_enabled() -> None:
    hub = _RecordingHub()
    ws = WorkspaceConfig(
        schema_version=1,
        self_improve={"enabled": True, "preset": "A"},
        channels={"telegram": {"allowed_users": [999]}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    fanout = SelfImproveJobEventFanout(hub=hub, telegram=None, workspace=ws)
    asyncio.run(
        fanout.publish(
            {
                "job_id": "jid1",
                "state": "queued",
                "event": "transition",
                "preset": "A",
            },
        ),
    )
    assert hub.events == [
        (
            "self_improve.job.jid1",
            {"job_id": "jid1", "state": "queued", "event": "transition", "preset": "A"},
        ),
    ]


def test_fanout_skips_when_self_improve_disabled() -> None:
    hub = _RecordingHub()
    tg = _RecordingTelegram()
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    fanout = SelfImproveJobEventFanout(hub=hub, telegram=tg, workspace=ws)
    asyncio.run(
        fanout.publish(
            {"job_id": "jid1", "state": "queued", "event": "transition", "preset": "A"},
        ),
    )
    assert hub.events == []
    assert tg.messages == []


def test_fanout_sends_telegram_when_enabled() -> None:
    hub = _RecordingHub()
    tg = _RecordingTelegram()
    ws = WorkspaceConfig(
        schema_version=1,
        self_improve={"enabled": True, "preset": "A"},
        channels={"telegram": {"allowed_users": [42]}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    fanout = SelfImproveJobEventFanout(hub=hub, telegram=tg, workspace=ws)
    asyncio.run(
        fanout.publish(
            {
                "job_id": "jid1",
                "state": "running",
                "event": "transition",
                "preset": "A",
            },
        ),
    )
    assert len(tg.messages) == 1
    assert tg.messages[0].user_id == "42"
    assert "[Self-improve]" in tg.messages[0].text
