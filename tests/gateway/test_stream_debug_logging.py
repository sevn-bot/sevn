"""W4 DEBUG structured logs for Telegram stream intermediates."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from sevn.channels.telegram import TelegramAdapter, TelegramConfig
from sevn.gateway.turn_finalizer import TierBAnswerFinalizer


class _StubAdapter:
    """Minimal adapter stub for finalizer stream_update tests."""

    def __init__(self) -> None:
        self.edits: list[dict[str, Any]] = []

    async def send(self, message: Any) -> list[str]:
        _ = message
        return ["42"]

    async def edit_text(
        self,
        *,
        channel_message_id: str,
        new_text: str,
        metadata: dict[str, Any] | None = None,
        send_split_followups: bool = True,
    ) -> bool:
        self.edits.append(
            {
                "channel_message_id": channel_message_id,
                "text": new_text,
                "metadata": dict(metadata or {}),
            },
        )
        return True


class _StubRouter:
    def cancel_telegram_typing(self, session_id: str) -> None:
        _ = session_id


def _json_response(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=data)


@pytest.mark.asyncio
async def test_stream_update_emits_telegram_stream_update_debug_event() -> None:
    """``stream_update`` logs ``telegram.stream_update`` with length + preview at DEBUG."""
    from loguru import logger as loguru_logger

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="DEBUG")
    try:
        adapter = _StubAdapter()
        fin = TierBAnswerFinalizer(
            router=_StubRouter(),  # type: ignore[arg-type]
            adapter=adapter,  # type: ignore[arg-type]
            channel="telegram",
            user_id="u1",
            session_id="sess-w4",
            turn_id="turn-w4",
            metadata={"chat_id": 9014},
        )
        await fin.place_placeholder()
        body = "Partial answer growing " + ("x" * 180)
        await fin.stream_update(body)
    finally:
        loguru_logger.remove(sink_id)

    blob = "\n".join(captured)
    assert "event=telegram.stream_update" in blob
    assert "session_id='sess-w4'" in blob
    assert "turn_id='turn-w4'" in blob
    assert "message_id='42'" in blob
    assert f"text_len={len(body.strip())}" in blob
    assert "changed_from_last=False" in blob
    assert adapter.edits


@pytest.mark.asyncio
async def test_edit_message_text_emits_telegram_stream_edit_debug_event() -> None:
    """``edit_message_text`` logs ``telegram.stream_edit`` before Bot API call."""
    from loguru import logger as loguru_logger

    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return _json_response({"ok": True, "result": {"message_id": 55}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        cfg = TelegramConfig(bot_token="dummy-token")
        adapter = TelegramAdapter(config=cfg, http_client=client)
        sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="DEBUG")
        try:
            ok = await adapter.edit_message_text(
                chat_id=123,
                message_id=55,
                text="Stream body for debug logging",
            )
        finally:
            loguru_logger.remove(sink_id)

    assert ok is True
    blob = "\n".join(captured)
    assert "event=telegram.stream_edit" in blob
    assert "chat_id=123" in blob
    assert "message_id=55" in blob
    assert "text_len=29" in blob
    assert "Stream body for debug logging" in blob
