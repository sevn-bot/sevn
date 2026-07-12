"""Attachment sends and empty-text guards (`specs/18-channel-telegram.md` §4.4, §10.16)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from sevn.channels.telegram import TelegramAdapter, TelegramConfig, TelegramSendError
from sevn.gateway.channel_router import OutgoingMessage


def _json_response(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=data)


@pytest.mark.asyncio
async def test_send_document_multipart_round_trip(tmp_path: Path) -> None:
    """``sendDocument`` uploads file bytes and returns ``message_id``."""
    doc = tmp_path / "skills_index.md"
    doc.write_text("# index\n", encoding="utf-8")
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert request.url.path.endswith("/sendDocument")
        return _json_response({"ok": True, "result": {"message_id": 9001}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = TelegramAdapter(config=TelegramConfig(bot_token="tok"), http_client=client)
        out = await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="1",
                text="caption here",
                session_id="s",
                metadata={
                    "chat_id": 42,
                    "attachment_path": str(doc),
                    "attachment_filename": "index.md",
                    "attachment_mime": "text/markdown",
                    "attachment_kind": "document",
                },
            ),
        )
        assert out == ["9001"]
        assert len(captured) == 1
        body = captured[0].content
        assert b"document" in body
        assert b"index.md" in body
        assert b"caption here" in body


@pytest.mark.asyncio
async def test_send_photo_uses_send_photo(tmp_path: Path) -> None:
    """``attachment_kind=photo`` maps to ``sendPhoto``."""
    photo = tmp_path / "shot.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\n")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/sendPhoto")
        return _json_response({"ok": True, "result": {"message_id": 12}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = TelegramAdapter(config=TelegramConfig(bot_token="tok"), http_client=client)
        out = await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="1",
                text="",
                session_id="s",
                metadata={
                    "chat_id": 1,
                    "attachment_path": str(photo),
                    "attachment_kind": "photo",
                },
            ),
        )
        assert out == ["12"]


@pytest.mark.asyncio
async def test_send_document_api_error_raises(tmp_path: Path) -> None:
    """Non-ok Bot API response surfaces ``TelegramSendError`` with description."""
    doc = tmp_path / "missing-on-disk.txt"
    doc.write_text("x", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {
                "ok": False,
                "error_code": 400,
                "description": "Bad Request: file must be non-empty",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = TelegramAdapter(config=TelegramConfig(bot_token="tok"), http_client=client)
        with pytest.raises(TelegramSendError) as exc_info:
            await adapter.send(
                OutgoingMessage(
                    channel="telegram",
                    user_id="1",
                    text="",
                    session_id="s",
                    metadata={
                        "chat_id": 1,
                        "attachment_path": str(doc),
                        "attachment_kind": "document",
                    },
                ),
            )
        assert "Bad Request" in exc_info.value.description


@pytest.mark.asyncio
async def test_send_text_empty_chunks_skips_api() -> None:
    """Whitespace-only body does not call ``sendMessage``."""
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.url.path)
        return _json_response({"ok": True, "result": {"message_id": 1}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = TelegramAdapter(config=TelegramConfig(bot_token="tok"), http_client=client)
        out = await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="1",
                text="   ",
                session_id="s",
                metadata={"chat_id": 9},
            ),
        )
        assert out == []
        assert captured == []


@pytest.mark.asyncio
async def test_edit_message_text_rejects_empty() -> None:
    """``editMessageText`` is not issued for blank text."""
    captured: list[str] = []

    async def _api(method: str, body: dict[str, Any]) -> dict[str, Any]:
        captured.append(method)
        return {"ok": True, "result": {"message_id": 1}}

    adapter = TelegramAdapter(config=TelegramConfig(bot_token="tok"))
    adapter._api = _api  # type: ignore[method-assign]
    ok = await adapter.edit_message_text(chat_id=1, message_id=2, text="")
    assert ok is False
    assert captured == []
    ok_ws = await adapter.edit_message_text(chat_id=1, message_id=2, text="   ")
    assert ok_ws is False
    assert captured == []
