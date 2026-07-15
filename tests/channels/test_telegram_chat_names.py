"""Group chat title persistence for session path names (#21; green after W2)."""

from __future__ import annotations

import sqlite3
from typing import Any

from sevn.channels.telegram import TelegramAdapter, TelegramConfig
from sevn.storage.migrate import apply_migrations


def _chat_names_table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'telegram_chat_names'",
    ).fetchone()
    return row is not None


def test_supergroup_message_persists_chat_title() -> None:
    """W1.4: inbound group message with ``chat.title`` upserts ``telegram_chat_names``."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    apply_migrations(conn)
    assert _chat_names_table_exists(conn), "telegram_chat_names table missing (green after W2)"
    adapter = TelegramAdapter(config=TelegramConfig(bot_token=""), sqlite_conn=conn)
    payload: dict[str, Any] = {
        "update_id": 100,
        "message": {
            "message_id": 1,
            "from": {"id": 42},
            "chat": {"id": -1001234567890, "type": "supergroup", "title": "My Group"},
            "text": "hello",
        },
    }
    msg = adapter.parse_webhook(payload)
    assert msg is not None
    row = conn.execute(
        "SELECT name FROM telegram_chat_names WHERE chat_id = ?",
        (-1001234567890,),
    ).fetchone()
    assert row is not None
    assert row[0] == "My Group"
    conn.close()


def test_supergroup_message_updates_chat_title_on_rename() -> None:
    """W1.4: subsequent inbound message updates stored group title."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    apply_migrations(conn)
    assert _chat_names_table_exists(conn), "telegram_chat_names table missing (green after W2)"
    adapter = TelegramAdapter(config=TelegramConfig(bot_token=""), sqlite_conn=conn)
    base: dict[str, Any] = {
        "message_id": 1,
        "from": {"id": 42},
        "chat": {"id": -55, "type": "supergroup", "title": "Old Name"},
        "text": "x",
    }
    adapter.parse_webhook({"update_id": 1, "message": base})
    renamed = dict(base)
    renamed["message_id"] = 2
    renamed["chat"] = {"id": -55, "type": "supergroup", "title": "New Name"}
    adapter.parse_webhook({"update_id": 2, "message": renamed})
    row = conn.execute(
        "SELECT name FROM telegram_chat_names WHERE chat_id = ?",
        (-55,),
    ).fetchone()
    assert row is not None
    assert row[0] == "New Name"
    conn.close()


def test_private_chat_message_does_not_require_chat_names_row() -> None:
    """D7: private DM messages must not upsert group title rows."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    apply_migrations(conn)
    adapter = TelegramAdapter(config=TelegramConfig(bot_token=""), sqlite_conn=conn)
    payload: dict[str, Any] = {
        "update_id": 200,
        "message": {
            "message_id": 1,
            "from": {"id": 99},
            "chat": {"id": 99, "type": "private", "first_name": "Alex"},
            "text": "dm",
        },
    }
    msg = adapter.parse_webhook(payload)
    assert msg is not None
    if _chat_names_table_exists(conn):
        count = conn.execute("SELECT COUNT(*) FROM telegram_chat_names").fetchone()
        assert count is not None
        assert int(count[0]) == 0
    conn.close()
