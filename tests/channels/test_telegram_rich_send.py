"""Tests for Telegram rich send/edit/draft integration (R4.1-R4.3, D4-D5)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from sevn.channels.telegram import (
    TELEGRAM_RICH_DRAFT_KEY,
    TELEGRAM_STREAMING_ACTIVE_KEY,
    TELEGRAM_USE_RICH_KEY,
    TelegramConfig,
)
from sevn.channels.telegram_capabilities import RichCapability
from sevn.channels.telegram_format import to_telegram
from sevn.config.sections.channels import TelegramRichConfig
from sevn.gateway.channel_router import OutgoingMessage
from tests.channels.test_markdown_safe import _MockTelegramAdapter

_TABLE = "| A | B |\n|---|---|\n| 1 | 2 |\n"


class _RichSendAdapter(_MockTelegramAdapter):
    """Captures Bot API calls and simulates rich capability."""

    def __init__(
        self,
        *,
        capability: RichCapability = RichCapability.CAPABLE,
        rich_mode: str = "auto",
        parse_mode: str = "HTML",
    ) -> None:
        super().__init__()
        self._cfg = TelegramConfig(
            bot_token="test-token",
            parse_mode=parse_mode,  # type: ignore[arg-type]
            rich=TelegramRichConfig(mode=rich_mode),  # type: ignore[arg-type]
        )
        self._rich_capability = capability
        self.trace_events: list[dict[str, Any]] = []

    @property
    def rich_capability(self) -> RichCapability:
        return self._rich_capability

    async def _emit_trace(self, **kwargs: Any) -> None:
        self.trace_events.append(dict(kwargs))


@pytest.mark.asyncio
async def test_send_rich_message_calls_send_rich_message_api() -> None:
    adapter = _RichSendAdapter()
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        mid = await adapter.send_rich_message(chat_id=7, markdown=_TABLE)
    assert mid == "4242"
    assert len(adapter.api_calls) == 1
    method, body = adapter.api_calls[0]
    assert method == "sendRichMessage"
    assert body["chat_id"] == 7
    # InputRichMessage is the raw Rich Markdown string, not a pre-rendered blocks tree.
    assert body["rich_message"] == {"markdown": _TABLE}


@pytest.mark.asyncio
async def test_send_rich_outbound_falls_back_on_api_failure() -> None:
    adapter = _RichSendAdapter()

    async def fail_rich(*_args: Any, **_kwargs: Any) -> str:
        raise ValueError("sendRichMessage failed")

    adapter.send_rich_message = fail_rich  # type: ignore[method-assign]

    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        ids = await adapter._send_rich_outbound(
            markdown=_TABLE,
            chat_id=9,
            thread_id=None,
            reply_to_int=None,
            disable_preview=False,
            reply_markup_first=None,
            edit_first=None,
            skip_text_edit=False,
            streaming_active=False,
        )
    assert ids == ["4242"]
    assert adapter.api_calls[0][0] == "sendMessage"
    assert adapter.trace_events
    assert adapter.trace_events[0]["kind"] == "channel.telegram.rich_fallback"


@pytest.mark.asyncio
async def test_send_uses_rich_path_when_metadata_hints() -> None:
    adapter = _RichSendAdapter()
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        out = await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="u",
                text=_TABLE,
                session_id="s",
                metadata={
                    "chat_id": 1,
                    TELEGRAM_USE_RICH_KEY: True,
                },
            ),
        )
    assert out == ["4242"]
    assert adapter.api_calls[0][0] == "sendRichMessage"


@pytest.mark.asyncio
async def test_streaming_placeholder_uses_persistent_rich_send() -> None:
    # sendRichMessageDraft is ephemeral and returns no message_id, so the streaming
    # placeholder is sent as a persistent sendRichMessage that later edits can target.
    adapter = _RichSendAdapter()
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        out = await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="u",
                text="…",
                session_id="s",
                metadata={
                    "chat_id": 1,
                    TELEGRAM_USE_RICH_KEY: True,
                    TELEGRAM_STREAMING_ACTIVE_KEY: True,
                    TELEGRAM_RICH_DRAFT_KEY: True,
                },
            ),
        )
    assert out == ["4242"]
    method, body = adapter.api_calls[0]
    assert method == "sendRichMessage"
    assert body["rich_message"] == {"markdown": "…"}


@pytest.mark.asyncio
async def test_send_rich_message_draft_uses_draft_id_and_returns_true() -> None:
    adapter = _RichSendAdapter()
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        ok = await adapter.send_rich_message_draft(chat_id=5, markdown=_TABLE, draft_id=99)
    assert ok is True
    method, body = adapter.api_calls[0]
    assert method == "sendRichMessageDraft"
    assert body["draft_id"] == 99
    assert body["rich_message"] == {"markdown": _TABLE}
    assert "message_id" not in body


@pytest.mark.asyncio
async def test_send_rich_message_draft_rejects_zero_draft_id() -> None:
    adapter = _RichSendAdapter()
    with (
        patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())),
        pytest.raises(ValueError, match="draft_id must be non-zero"),
    ):
        await adapter.send_rich_message_draft(chat_id=5, markdown=_TABLE, draft_id=0)


@pytest.mark.asyncio
async def test_edit_rich_message_uses_rich_message_field() -> None:
    adapter = _RichSendAdapter()
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        ok = await adapter.edit_rich_message(
            chat_id=3,
            message_id=50,
            markdown=_TABLE,
        )
    assert ok is True
    method, body = adapter.api_calls[0]
    assert method == "editMessageText"
    assert "rich_message" in body
    assert "text" not in body


@pytest.mark.asyncio
async def test_edit_text_streaming_rich_then_fallback() -> None:
    adapter = _RichSendAdapter()

    async def fail_rich(**_kwargs: Any) -> bool:
        raise ValueError("parse error")

    adapter.edit_rich_message = fail_rich  # type: ignore[method-assign]

    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        ok = await adapter.edit_text(
            channel_message_id="50",
            new_text=_TABLE,
            metadata={
                "chat_id": 3,
                TELEGRAM_STREAMING_ACTIVE_KEY: True,
                TELEGRAM_USE_RICH_KEY: True,
            },
            send_split_followups=False,
        )
    assert ok is True
    assert adapter.api_calls[0][0] == "editMessageText"
    assert "text" in adapter.api_calls[0][1]
    assert adapter.api_calls[0][1]["text"] == to_telegram(_TABLE, "HTML")


@pytest.mark.asyncio
async def test_send_rich_attaches_reply_markup() -> None:
    adapter = _RichSendAdapter()
    kb = {"inline_keyboard": [[{"text": "OK", "callback_data": "ok"}]]}
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        await adapter.send_rich_message(chat_id=2, markdown=_TABLE, reply_markup=kb)
    _method, body = adapter.api_calls[0]
    assert body["reply_markup"] == kb


@pytest.mark.asyncio
async def test_not_capable_skips_rich_send() -> None:
    adapter = _RichSendAdapter(capability=RichCapability.NOT_CAPABLE)
    with patch.object(adapter, "_ensure_client", AsyncMock(return_value=object())):
        out = await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="u",
                text=_TABLE,
                session_id="s",
                metadata={"chat_id": 1, TELEGRAM_USE_RICH_KEY: True},
            ),
        )
    assert out == ["4242"]
    assert adapter.api_calls[0][0] == "sendMessage"


def test_smoke_post_split_telegram_rich_outbound_import() -> None:
    """W5: adapter delegates rich outbound to extracted helper module."""
    import importlib

    importlib.import_module("sevn.channels.telegram_rich_outbound")
