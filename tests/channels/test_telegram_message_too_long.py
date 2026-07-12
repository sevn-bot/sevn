"""W6 — ``MESSAGE_TOO_LONG`` split fallback on ``editMessageText``."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from sevn.channels.telegram import TelegramAdapter, TelegramConfig, chunk_text


def _json_response(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=data)


@pytest.mark.asyncio
async def test_edit_message_text_splits_on_message_too_long() -> None:
    """Stub ``MESSAGE_TOO_LONG`` on full-body edit → split + follow-up ``sendMessage``."""
    long_body = "segment\n" * 2500
    chunks = chunk_text(long_body)
    assert len(chunks) >= 2

    calls: list[tuple[str, dict[str, Any]]] = []
    send_mid = {"n": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        payload = json.loads(request.content.decode())
        calls.append((method, payload))
        if method == "editMessageText":
            if len(payload.get("text", "")) > 4200:
                return _json_response(
                    {
                        "ok": False,
                        "error_code": 400,
                        "description": "Bad Request: message is too long",
                    },
                )
            return _json_response({"ok": True, "result": {"message_id": 100}})
        if method == "sendMessage":
            send_mid["n"] += 1
            return _json_response({"ok": True, "result": {"message_id": send_mid["n"]}})
        return _json_response({"ok": True, "result": {"message_id": 100}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = TelegramAdapter(config=TelegramConfig(bot_token="tok"), http_client=client)
        ok = await adapter.edit_message_text(
            chat_id=42,
            message_id=100,
            text=long_body,
            send_split_followups=True,
        )

    assert ok is True
    edit_calls = [p for m, p in calls if m == "editMessageText"]
    send_calls = [p for m, p in calls if m == "sendMessage"]
    assert edit_calls
    assert len(send_calls) == len(chunks) - 1
    recovered = edit_calls[-1]["text"] + "".join(c["text"] for c in send_calls)
    assert recovered == long_body


@pytest.mark.asyncio
async def test_edit_message_text_stream_defers_followups() -> None:
    """Streaming path edits chunk 0 only when ``send_split_followups=False``."""
    long_body = "word " * 1200
    chunks = chunk_text(long_body)
    assert len(chunks) >= 2

    calls: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        payload = json.loads(request.content.decode())
        calls.append((method, payload))
        return _json_response({"ok": True, "result": {"message_id": 100}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = TelegramAdapter(config=TelegramConfig(bot_token="tok"), http_client=client)
        ok = await adapter.edit_message_text(
            chat_id=42,
            message_id=100,
            text=long_body,
            send_split_followups=False,
        )

    assert ok is True
    assert [m for m, _ in calls] == ["editMessageText"]
    assert calls[0][1]["text"] == chunks[0]
