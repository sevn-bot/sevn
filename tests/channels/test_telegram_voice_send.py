"""Tests for ``TelegramAdapter._send_voice`` (`specs/18-channel-telegram.md` §4.4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from sevn.channels.telegram import TelegramAdapter, TelegramConfig
from sevn.gateway.channel_router import OutgoingMessage


def _json_response(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=data)


@pytest.mark.asyncio
async def test_send_voice_round_trip(tmp_path: Path) -> None:
    """Recorded ``sendVoice`` fixture: OGG upload returns Telegram ``message_id``."""

    voice_file = tmp_path / "reply.ogg"
    voice_file.write_bytes(b"OggS\x00fake-opus-bytes")

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert request.url.path.endswith("/sendVoice")
        return _json_response({"ok": True, "result": {"message_id": 4421}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        cfg = TelegramConfig(bot_token="dummy-token-for-tests")
        adapter = TelegramAdapter(config=cfg, http_client=client)
        out = await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="1",
                text="",
                session_id="s",
                metadata={"chat_id": -100555, "tts_audio_path": str(voice_file)},
            ),
        )
        assert out == ["4421"]
        assert len(captured) == 1
        body = captured[0].content
        assert b"voice" in body
        assert b"reply.ogg" in body
        assert b"audio/ogg" in body
        assert b"-100555" in body


@pytest.mark.asyncio
async def test_send_voice_mp3_mime(tmp_path: Path) -> None:
    """MP3 TTS output uses ``audio/mpeg`` for ``sendVoice``."""

    voice_file = tmp_path / "reply.mp3"
    voice_file.write_bytes(b"\xff\xfb\x90\x00fake-mp3")

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response({"ok": True, "result": {"message_id": 99}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        cfg = TelegramConfig(bot_token="x")
        adapter = TelegramAdapter(config=cfg, http_client=client)
        out = await adapter._send_voice(-1001, str(voice_file), thread_id=None)
        assert out == ["99"]
        assert captured
        assert b"audio/mpeg" in captured[0].content
        assert b"reply.mp3" in captured[0].content


@pytest.mark.asyncio
async def test_send_voice_thread_id_propagation(tmp_path: Path) -> None:
    """Forum topic ``message_thread_id`` is included in the multipart form."""

    voice_file = tmp_path / "topic.ogg"
    voice_file.write_bytes(b"OggS\x00topic-voice")

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response({"ok": True, "result": {"message_id": 808}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        cfg = TelegramConfig(bot_token="x")
        adapter = TelegramAdapter(config=cfg, http_client=client)
        out = await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="1",
                text="",
                session_id="s",
                metadata={
                    "chat_id": 42,
                    "topic_id": 17,
                    "tts_audio_path": str(voice_file),
                },
            ),
        )
        assert out == ["808"]
        assert captured
        body = captured[0].content
        assert b"message_thread_id" in body
        assert b"17" in body
