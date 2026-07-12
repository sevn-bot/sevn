"""Messaging channel adapters.

Module: sevn.channels
Depends: gateway router contracts (`specs/17-gateway.md`, `specs/18`, `specs/19`)

Exports:
    DMPolicy — DM access policy enum.
    TelegramAdapter — Telegram Bot API adapter.
    TelegramConfig — resolved adapter configuration.
    TopicConfig — forum topic overrides.
    WebChatAdapter — web UI WebSocket adapter (`specs/19-channel-webui.md`).
    WebChatConfig — resolved web UI channel settings.
    chunk_text — UTF-16-safe outbound chunking.
    format_reply_quote — reply-quote prefix builder.
    telegram_callback_data_utf8_len — UTF-8 byte length for Telegram ``callback_data``.
    telegram_config_from_workspace — build config from ``sevn.json``.
    telegram_utf16_len — Telegram UTF-16 length helper.
    tokenize_inline_keyboard_callback_data — persist overflow callback payloads.
    resolve_dispatcher_overflow_callback_data — expand ``ds:`` callback tokens.
    webchat_config_from_workspace — build :class:`WebChatConfig` from ``sevn.json``.
"""

from __future__ import annotations

from sevn.channels.callback_overflow import (
    resolve_dispatcher_overflow_callback_data,
    telegram_callback_data_utf8_len,
    tokenize_inline_keyboard_callback_data,
)
from sevn.channels.telegram import (
    DMPolicy,
    TelegramAdapter,
    TelegramConfig,
    TopicConfig,
    chunk_text,
    format_reply_quote,
    telegram_config_from_workspace,
    telegram_utf16_len,
)
from sevn.channels.webchat import WebChatAdapter, WebChatConfig, webchat_config_from_workspace

__all__ = [
    "DMPolicy",
    "TelegramAdapter",
    "TelegramConfig",
    "TopicConfig",
    "WebChatAdapter",
    "WebChatConfig",
    "chunk_text",
    "format_reply_quote",
    "resolve_dispatcher_overflow_callback_data",
    "telegram_callback_data_utf8_len",
    "telegram_config_from_workspace",
    "telegram_utf16_len",
    "tokenize_inline_keyboard_callback_data",
    "webchat_config_from_workspace",
]
