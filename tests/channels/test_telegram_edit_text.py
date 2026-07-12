"""Tests for ``TelegramAdapter.edit_text`` (PROBLEMS.md Priority 2)."""

from __future__ import annotations

from typing import Any

import pytest

from sevn.channels.telegram import TelegramAdapter


class _TelegramAdapterUnderTest(TelegramAdapter):
    """Captures edit_message_text calls without hitting the real Bot API."""

    def __init__(self) -> None:
        super().__init__(resolved_bot_token="test-token")
        self.calls: list[dict[str, Any]] = []
        self.return_value: bool = True

    async def edit_message_text(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        message_thread_id: int | None = None,
        send_split_followups: bool = True,
    ) -> bool:
        self.calls.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "message_thread_id": message_thread_id,
                "reply_markup": reply_markup,
            },
        )
        return self.return_value


@pytest.mark.asyncio
async def test_edit_text_delegates_to_edit_message_text() -> None:
    adapter = _TelegramAdapterUnderTest()
    ok = await adapter.edit_text(
        channel_message_id="42",
        new_text="new body",
        metadata={"chat_id": 7, "telegram_thread_id": 11},
    )
    assert ok is True
    assert adapter.calls == [
        {
            "chat_id": 7,
            "message_id": 42,
            "text": "new body",
            "message_thread_id": 11,
            "reply_markup": None,
        }
    ]


@pytest.mark.asyncio
async def test_edit_text_returns_false_when_message_id_non_integer() -> None:
    adapter = _TelegramAdapterUnderTest()
    assert (
        await adapter.edit_text(
            channel_message_id="not-an-int",
            new_text="x",
            metadata={"chat_id": 7},
        )
        is False
    )
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_edit_text_returns_false_when_chat_id_missing() -> None:
    adapter = _TelegramAdapterUnderTest()
    assert await adapter.edit_text(channel_message_id="42", new_text="x", metadata={}) is False
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_edit_text_accepts_topic_id_alias() -> None:
    """Adapters use either ``telegram_thread_id`` or ``topic_id`` for forum threads."""
    adapter = _TelegramAdapterUnderTest()
    await adapter.edit_text(
        channel_message_id="42",
        new_text="x",
        metadata={"chat_id": 7, "topic_id": 5},
    )
    assert adapter.calls[0]["message_thread_id"] == 5


@pytest.mark.asyncio
async def test_edit_text_rejects_empty_and_whitespace_without_api_call() -> None:
    """Empty-text guard: no ``editMessageText`` for blank bodies."""
    adapter = _TelegramAdapterUnderTest()
    assert (
        await adapter.edit_text(
            channel_message_id="42",
            new_text="",
            metadata={"chat_id": 7},
        )
        is False
    )
    assert (
        await adapter.edit_text(
            channel_message_id="42",
            new_text="   ",
            metadata={"chat_id": 7},
        )
        is False
    )
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_edit_text_returns_false_when_provider_reports_failure() -> None:
    adapter = _TelegramAdapterUnderTest()
    adapter.return_value = False
    ok = await adapter.edit_text(
        channel_message_id="42",
        new_text="x",
        metadata={"chat_id": 7},
    )
    assert ok is False


@pytest.mark.asyncio
async def test_default_channel_adapter_edit_text_returns_false() -> None:
    """The abstract default means "not supported" so unconverted adapters stay safe."""
    from sevn.gateway.channel_router import ChannelAdapter, IncomingMessage, OutgoingMessage

    class _Minimal(ChannelAdapter):
        @property
        def name(self) -> str:
            return "minimal"

        def parse_webhook(self, payload: dict[str, Any]) -> IncomingMessage | None:
            return None

        async def send(self, message: OutgoingMessage) -> list[str]:
            return []

    adapter = _Minimal()
    assert await adapter.edit_text(channel_message_id="x", new_text="y", metadata={}) is False
