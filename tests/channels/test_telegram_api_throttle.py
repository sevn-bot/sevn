"""RED suite for Telegram ``sendChatAction`` coalescing (D5; green after W5)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from sevn.channels.telegram import TelegramAdapter, TelegramConfig


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W5: coalesce sendChatAction", strict=False)
async def test_send_chat_action_coalesced_within_window() -> None:
    """D5: typing indicator is sent at most once per coalesce window per chat."""
    calls: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = httpx.Request("", "POST", content=request.content).content
        import json

        payload = json.loads(body.decode())
        calls.append((request.url.path.split("/")[-1], payload))
        return httpx.Response(200, json={"ok": True, "result": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = TelegramAdapter(config=TelegramConfig(bot_token="tok"), http_client=client)
        chat_id = 9001
        for _ in range(8):
            await adapter.send_chat_action(chat_id=chat_id)
            await asyncio.sleep(0)
    action_calls = [method for method, _body in calls if method == "sendChatAction"]
    assert len(action_calls) <= 1


@pytest.mark.asyncio
async def test_send_chat_action_still_reaches_api_today() -> None:
    """Baseline: each call currently reaches the Bot API (pre-coalesce behavior)."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path.split("/")[-1])
        return httpx.Response(200, json={"ok": True, "result": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = TelegramAdapter(config=TelegramConfig(bot_token="tok"), http_client=client)
        await adapter.send_chat_action(chat_id=42)
        await adapter.send_chat_action(chat_id=42)
    assert calls.count("sendChatAction") == 2
