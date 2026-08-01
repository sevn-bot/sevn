"""Buzz channel adapter smoke tests (#72, W31)."""

from __future__ import annotations

from sevn.acp.buzz_config import BuzzIdentity
from sevn.channels.buzz import BuzzChannelAdapter
from sevn.gateway.channel_types import OutgoingMessage


def test_buzz_parse_mention_webhook() -> None:
    adapter = BuzzChannelAdapter()
    msg = adapter.parse_webhook(
        {
            "event": "mention",
            "mention": True,
            "channel": {"id": "ch1"},
            "message": {
                "text": "@sevn ping",
                "author": {"id": "user-1"},
            },
        }
    )
    assert msg is not None
    assert msg.channel == "buzz"
    assert msg.user_id == "user-1"
    assert "ping" in msg.text


def test_buzz_send_without_identity_is_noop() -> None:
    import asyncio

    ids = asyncio.run(
        BuzzChannelAdapter().send(
            OutgoingMessage(
                channel="buzz",
                user_id="user-1",
                text="hi",
                metadata={"channel_id": "ch1"},
            )
        )
    )
    assert ids == []


def test_buzz_send_with_identity_posts() -> None:
    import asyncio

    class _FakeResponse:
        status_code = 200
        content = b'{"id":"m1"}'

        def json(self) -> dict[str, str]:
            return {"id": "m1"}

    class _FakeClient:
        async def post(self, *_args: object, **_kwargs: object) -> _FakeResponse:
            return _FakeResponse()

        async def aclose(self) -> None:
            return None

    adapter = BuzzChannelAdapter(
        identity=BuzzIdentity(relay_url="https://relay.test", private_key="k"),
        http_client=_FakeClient(),  # type: ignore[arg-type]
    )
    ids = asyncio.run(
        adapter.send(
            OutgoingMessage(
                channel="buzz",
                user_id="user-1",
                text="hello",
                metadata={"channel_id": "ch1"},
            )
        )
    )
    assert ids == ["m1"]
