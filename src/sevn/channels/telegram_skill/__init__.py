"""Telegram skill helpers for bundled ``telegram`` scripts (`specs/18-channel-telegram.md`).

Module: sevn.channels.telegram_skill
Depends: sevn.channels.telegram_skill.buttons, sevn.channels.telegram_skill.forum, sevn.channels.telegram_skill.hooks

Exports:
    TelegramSkillHooks — injectable Bot API and userbot delegates.
    buttons_store_path — workspace-relative custom button store path.
    list_custom_buttons — list stored custom inline buttons.
    add_custom_button — add one custom button row.
    remove_custom_button — remove by display name.
    clear_custom_buttons — remove all custom buttons.
    build_custom_inline_keyboard — two-column inline keyboard from store.
    create_forum_topic — create a forum topic via Bot API hook.
    find_group_by_name — resolve supergroup chat id by title via hooks.
    resolve_telegram_skill_hooks — default hooks from env + workspace config.
"""

from __future__ import annotations

from sevn.channels.telegram_skill.buttons import (
    add_custom_button,
    build_custom_inline_keyboard,
    buttons_store_path,
    clear_custom_buttons,
    list_custom_buttons,
    remove_custom_button,
)
from sevn.channels.telegram_skill.forum import create_forum_topic, find_group_by_name
from sevn.channels.telegram_skill.hooks import TelegramSkillHooks, resolve_telegram_skill_hooks

__all__ = [
    "TelegramSkillHooks",
    "add_custom_button",
    "build_custom_inline_keyboard",
    "buttons_store_path",
    "clear_custom_buttons",
    "create_forum_topic",
    "find_group_by_name",
    "list_custom_buttons",
    "remove_custom_button",
    "resolve_telegram_skill_hooks",
]
