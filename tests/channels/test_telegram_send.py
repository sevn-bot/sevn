"""Tests for ``TelegramAdapter.send`` (`specs/18-channel-telegram.md`); no live network."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from sevn.channels.telegram import TelegramAdapter, TelegramConfig, chunk_text
from sevn.gateway.channel_router import OutgoingMessage


def _json_response(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=data)


@pytest.mark.asyncio
async def test_send_returns_telegram_message_ids_mocked() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        calls.append((request.url.path.split("/")[-1], body))
        return _json_response({"ok": True, "result": {"message_id": 901}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        cfg = TelegramConfig(bot_token="dummy-token-for-tests")
        adapter = TelegramAdapter(config=cfg, http_client=client)
        out = await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="1",
                text="hello",
                session_id="s",
                metadata={"chat_id": -100123, "message_id": 1},
            ),
        )
        assert out == ["901"]
        assert calls
        assert calls[0][0] == "sendMessage"


@pytest.mark.asyncio
async def test_send_empty_text_returns_empty_list() -> None:
    transport = httpx.MockTransport(
        lambda r: _json_response({"ok": True, "result": {"message_id": 1}}),
    )
    async with httpx.AsyncClient(transport=transport) as client:
        cfg = TelegramConfig(bot_token="x")
        adapter = TelegramAdapter(config=cfg, http_client=client)
        out = await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="1",
                text="",
                session_id="s",
                metadata={"chat_id": 1},
            ),
        )
        assert out == []


@pytest.mark.asyncio
async def test_send_edit_first_chunk_only() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.url.path.split("/")[-1])
        return _json_response({"ok": True, "result": {"message_id": 77}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        cfg = TelegramConfig(bot_token="x")
        adapter = TelegramAdapter(config=cfg, http_client=client)
        long_body = "a\n" * 3000
        chunks = chunk_text(long_body)
        assert len(chunks) > 1
        out = await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="1",
                text=long_body,
                session_id="s",
                metadata={"chat_id": 1, "edit_message_id": 50},
            ),
        )
        assert "editMessageText" in methods
        assert "sendMessage" in methods
        assert len(out) == len(chunks)


@pytest.mark.asyncio
async def test_send_tokenizes_long_callback_data_in_keyboard() -> None:
    import sqlite3

    from sevn.channels.callback_overflow import telegram_callback_data_utf8_len
    from sevn.storage.migrate import apply_migrations

    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        b = json.loads(request.content.decode())
        bodies.append(b)
        return _json_response({"ok": True, "result": {"message_id": 901}})

    transport = httpx.MockTransport(handler)
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    long_cb = "qa:" + "y" * 90
    markup = {"inline_keyboard": [[{"text": "go", "callback_data": long_cb}]]}
    async with httpx.AsyncClient(transport=transport) as client:
        cfg = TelegramConfig(bot_token="dummy-token-for-tests")
        adapter = TelegramAdapter(config=cfg, http_client=client, sqlite_conn=conn)
        await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="1",
                text="hello",
                session_id="s",
                metadata={"chat_id": 42, "inline_keyboard": markup},
            ),
        )
    assert bodies
    rm = bodies[0].get("reply_markup")
    assert isinstance(rm, dict)
    cb = rm["inline_keyboard"][0][0]["callback_data"]
    assert isinstance(cb, str)
    assert cb.startswith("ds:")
    assert telegram_callback_data_utf8_len(cb) <= 64
    row = conn.execute(
        "SELECT COUNT(*) FROM dispatcher_state WHERE kind='callback_overflow'"
    ).fetchone()
    assert row is not None
    assert int(row[0]) >= 1
    conn.close()


@pytest.mark.asyncio
async def test_send_retries_on_429_then_ok() -> None:
    n = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        n["i"] += 1
        if n["i"] < 2:
            return _json_response(
                {"ok": False, "error_code": 429, "parameters": {"retry_after": 0.01}},
            )
        return _json_response({"ok": True, "result": {"message_id": 3}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        cfg = TelegramConfig(bot_token="x")
        adapter = TelegramAdapter(config=cfg, http_client=client)
        out = await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="1",
                text="hi",
                session_id="s",
                metadata={"chat_id": 1},
            ),
        )
        assert out == ["3"]
        assert n["i"] == 2


def test_chunk_text_respects_utf16_cap() -> None:
    s = "é" * 3000
    chunks = chunk_text(s, max_utf16=100)
    assert all(len(c.encode("utf-16-le")) // 2 <= 100 for c in chunks)
