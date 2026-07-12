"""Reply-keyboard discoverability on tier-A Telegram outbound (recovery Wave B3)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from sevn.channels.telegram import (
    TelegramAdapter,
    TelegramConfig,
    build_reply_keyboard_markup,
)
from sevn.config.workspace_config import (
    ChannelsWorkspaceSectionConfig,
    TelegramChannelConfig,
    TelegramReplyKeyboardConfig,
    WorkspaceConfig,
)
from sevn.gateway.channel_router import OutgoingMessage
from sevn.gateway.telegram_quick_actions import GATEWAY_OUTBOUND_PHASE_KEY


def _json_response(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=data)


def _tier_a_metadata(*, chat_id: int = 42) -> dict[str, Any]:
    return {
        "chat_id": chat_id,
        GATEWAY_OUTBOUND_PHASE_KEY: "final",
    }


@pytest.mark.asyncio
async def test_first_tier_a_reply_attaches_reply_keyboard() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content.decode()))
        return _json_response({"ok": True, "result": {"message_id": 100}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        cfg = TelegramConfig(bot_token="test-token", reply_keyboard_enabled=True)
        adapter = TelegramAdapter(config=cfg, http_client=client)
        await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="1",
                text="Hello from tier A",
                session_id="sess-1",
                metadata=_tier_a_metadata(),
            ),
        )
        assert len(bodies) == 1
        markup = bodies[0].get("reply_markup")
        assert markup == build_reply_keyboard_markup()
        assert 42 in adapter._reply_keyboard_chats


@pytest.mark.asyncio
async def test_reply_keyboard_opt_out_suppresses_attachment() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content.decode()))
        return _json_response({"ok": True, "result": {"message_id": 101}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        cfg = TelegramConfig(bot_token="test-token", reply_keyboard_enabled=False)
        adapter = TelegramAdapter(config=cfg, http_client=client)
        await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="1",
                text="No keyboard",
                session_id="sess-2",
                metadata=_tier_a_metadata(chat_id=99),
            ),
        )
        assert "reply_markup" not in bodies[0]
        assert 99 not in adapter._reply_keyboard_chats


@pytest.mark.asyncio
async def test_subsequent_tier_a_replies_do_not_reattach_keyboard() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content.decode()))
        return _json_response({"ok": True, "result": {"message_id": 102}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        cfg = TelegramConfig(bot_token="test-token", reply_keyboard_enabled=True)
        adapter = TelegramAdapter(config=cfg, http_client=client)
        meta = _tier_a_metadata(chat_id=7)
        msg = OutgoingMessage(
            channel="telegram",
            user_id="1",
            text="first",
            session_id="sess-3",
            metadata=meta,
        )
        await adapter.send(msg)
        await adapter.send(
            OutgoingMessage(
                channel="telegram",
                user_id="1",
                text="second",
                session_id="sess-3",
                metadata=meta,
            ),
        )
        assert len(bodies) == 2
        assert bodies[0].get("reply_markup") == build_reply_keyboard_markup()
        assert "reply_markup" not in bodies[1]


def test_workspace_reply_keyboard_enabled_default_true() -> None:
    ws = WorkspaceConfig(
        schema_version=1,
        channels=ChannelsWorkspaceSectionConfig(
            telegram=TelegramChannelConfig(),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    from sevn.channels.telegram import telegram_config_from_workspace

    cfg = telegram_config_from_workspace(ws, bot_token="t")
    assert cfg.reply_keyboard_enabled is True


def test_workspace_reply_keyboard_opt_out() -> None:
    ws = WorkspaceConfig(
        schema_version=1,
        channels=ChannelsWorkspaceSectionConfig(
            telegram=TelegramChannelConfig(
                reply_keyboard=TelegramReplyKeyboardConfig(enabled=False),
            ),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    from sevn.channels.telegram import telegram_config_from_workspace

    cfg = telegram_config_from_workspace(ws, bot_token="t")
    assert cfg.reply_keyboard_enabled is False
