"""Discord and Slack adapter smoke tests (Batch H M2)."""

from __future__ import annotations

from sevn.channels.discord import DiscordChannelAdapter
from sevn.channels.slack import SlackChannelAdapter
from sevn.gateway.channel_router import OutgoingMessage


def test_discord_parse_message_create() -> None:
    adapter = DiscordChannelAdapter()
    msg = adapter.parse_webhook(
        {
            "d": {
                "content": "hello",
                "channel_id": "99",
                "author": {"id": "42"},
            }
        }
    )
    assert msg is not None
    assert msg.channel == "discord"
    assert msg.user_id == "42"
    assert msg.text == "hello"


def test_slack_parse_event_callback() -> None:
    adapter = SlackChannelAdapter()
    msg = adapter.parse_webhook(
        {
            "type": "event_callback",
            "event": {"type": "message", "user": "U1", "channel": "C1", "text": "ping"},
        }
    )
    assert msg is not None
    assert msg.channel == "slack"
    assert msg.text == "ping"


def test_discord_send_without_token_is_noop() -> None:
    import asyncio

    ids = asyncio.run(
        DiscordChannelAdapter().send(
            OutgoingMessage(
                channel="discord", user_id="42", text="hi", metadata={"channel_id": "99"}
            )
        )
    )
    assert ids == []
