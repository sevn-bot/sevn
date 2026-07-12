"""Quick-action markup must attach on a no-op final edit (`specs/18-channel-telegram.md` §4.5).

Regression for the "buttons missing intermittently" bug: when streaming already
pushed the exact final text to the placeholder, the ``phase="final"``
``editMessageText`` is a no-op and Telegram returns 400 "message is not
modified". The 👍/👎/regen bar must still land via a markup-only
``editMessageReplyMarkup`` rather than being dropped with the failed text edit.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from sevn.channels.telegram import TelegramAdapter, TelegramConfig
from sevn.gateway.channel_router import OutgoingMessage
from sevn.gateway.telegram_quick_actions import build_quick_action_inline_keyboard


def _json_response(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=data)


@pytest.mark.asyncio
async def test_final_noop_edit_still_attaches_quick_action_markup() -> None:
    """A no-op final ``editMessageText`` (400 not-modified) still attaches the QA bar."""
    calls: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        method = request.url.path.rsplit("/", 1)[-1]
        raw = request.read()
        payload = _json.loads(raw.decode()) if raw else {}
        calls.append((method, payload))
        if method == "editMessageText":
            # Streaming already wrote the identical body to the placeholder.
            return _json_response(
                {
                    "ok": False,
                    "error_code": 400,
                    "description": (
                        "Bad Request: message is not modified: specified new message "
                        "content and reply markup are exactly the same as a current "
                        "content and reply markup of the message"
                    ),
                },
            )
        if method == "editMessageReplyMarkup":
            return _json_response({"ok": True, "result": {"message_id": 100}})
        return _json_response({"ok": True, "result": {"message_id": 100}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = TelegramAdapter(config=TelegramConfig(bot_token="tok"), http_client=client)
        kb = build_quick_action_inline_keyboard(100)
        out = await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="1",
                text="final answer body",
                session_id="s",
                metadata={
                    "chat_id": 42,
                    "edit_message_id": 100,
                    "inline_keyboard": kb,
                },
            ),
        )

    methods = [m for m, _ in calls]
    # The no-op text edit is followed by a markup-only edit that lands the bar.
    assert "editMessageText" in methods
    assert "editMessageReplyMarkup" in methods
    # The send reports the edited message id (success), not an empty/failed result.
    assert out == ["100"]
    markup_payload = next(p for m, p in calls if m == "editMessageReplyMarkup")
    rows = markup_payload["reply_markup"]["inline_keyboard"][0]
    actions = [c["callback_data"] for c in rows]
    assert "qa:100:regen" in actions
    assert "qa:100:up" in actions
    assert "qa:100:down" in actions


@pytest.mark.asyncio
async def test_final_edit_with_changed_text_carries_markup_on_text_edit() -> None:
    """When the body differs, the single ``editMessageText`` already carries the bar."""
    calls: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        method = request.url.path.rsplit("/", 1)[-1]
        raw = request.read()
        payload = _json.loads(raw.decode()) if raw else {}
        calls.append((method, payload))
        return _json_response({"ok": True, "result": {"message_id": 101}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = TelegramAdapter(config=TelegramConfig(bot_token="tok"), http_client=client)
        kb = build_quick_action_inline_keyboard(101)
        out = await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="1",
                text="a brand new final body",
                session_id="s",
                metadata={
                    "chat_id": 42,
                    "edit_message_id": 101,
                    "inline_keyboard": kb,
                },
            ),
        )

    methods = [m for m, _ in calls]
    assert methods == ["editMessageText"]
    assert out == ["101"]
    text_payload = calls[0][1]
    rows = text_payload["reply_markup"]["inline_keyboard"][0]
    assert "qa:101:regen" in [c["callback_data"] for c in rows]
