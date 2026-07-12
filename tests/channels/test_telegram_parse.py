"""Tests for ``TelegramAdapter.parse_webhook`` (`specs/18-channel-telegram.md`)."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from sevn.channels.telegram import DMPolicy, TelegramAdapter, TelegramConfig, format_reply_quote


def test_parse_webhook_happy_path_message_text() -> None:
    adapter = TelegramAdapter()
    payload: dict[str, Any] = {
        "update_id": 1,
        "message": {
            "message_id": 9,
            "from": {"id": 42},
            "chat": {"id": 99, "type": "private"},
            "text": "  hello  ",
        },
    }
    msg = adapter.parse_webhook(payload)
    assert msg is not None
    assert msg.channel == "telegram"
    assert msg.user_id == "42"
    assert msg.text == "hello"
    assert msg.metadata.get("chat_id") == 99
    assert msg.metadata.get("telegram_chat_id") == "99"
    assert msg.metadata.get("session_scope_override") == "telegram:99:general"


def test_parse_webhook_edited_message_variant() -> None:
    adapter = TelegramAdapter()
    payload: dict[str, Any] = {
        "update_id": 2,
        "edited_message": {
            "message_id": 3,
            "from": {"id": 1},
            "chat": {"id": 2, "type": "private"},
            "text": "edited",
        },
    }
    msg = adapter.parse_webhook(payload)
    assert msg is not None
    assert msg.text == "edited"
    assert msg.user_id == "1"
    assert msg.metadata.get("is_edited_message") is True


def test_parse_webhook_dedupe_second_returns_none() -> None:
    adapter = TelegramAdapter()
    payload: dict[str, Any] = {
        "update_id": 99,
        "message": {
            "message_id": 1,
            "from": {"id": 1},
            "chat": {"id": 1, "type": "private"},
            "text": "once",
        },
    }
    assert adapter.parse_webhook(payload) is not None
    assert adapter.parse_webhook(payload) is None


def test_parse_webhook_dm_allowlist_denies() -> None:
    cfg = TelegramConfig(bot_token="", dm_policy=DMPolicy.ALLOWLIST, allowed_users=[7])
    adapter = TelegramAdapter(config=cfg)
    payload: dict[str, Any] = {
        "update_id": 10,
        "message": {
            "message_id": 1,
            "from": {"id": 8},
            "chat": {"id": 8, "type": "private"},
            "text": "nope",
        },
    }
    assert adapter.parse_webhook(payload) is None


def test_parse_webhook_group_restricted_by_chat_id() -> None:
    cfg = TelegramConfig(bot_token="", allowed_groups=[-100])
    adapter = TelegramAdapter(config=cfg)
    denied: dict[str, Any] = {
        "update_id": 11,
        "message": {
            "message_id": 1,
            "from": {"id": 1},
            "chat": {"id": -200, "type": "supergroup"},
            "text": "x",
        },
    }
    assert adapter.parse_webhook(denied) is None
    ok: dict[str, Any] = {
        "update_id": 12,
        "message": {
            "message_id": 2,
            "from": {"id": 1},
            "chat": {"id": -100, "type": "supergroup"},
            "text": "y",
        },
    }
    m = adapter.parse_webhook(ok)
    assert m is not None
    assert m.text == "y"


def test_parse_webhook_topic_ignored() -> None:
    from sevn.channels.telegram import TopicConfig

    cfg2 = TelegramConfig(bot_token="", topics={5: TopicConfig(topic_id=5, ignored=True)})
    adapter = TelegramAdapter(config=cfg2)
    payload: dict[str, Any] = {
        "update_id": 20,
        "message": {
            "message_id": 1,
            "from": {"id": 1},
            "chat": {"id": -100, "type": "supergroup"},
            "message_thread_id": 5,
            "text": "ignored topic",
        },
    }
    assert adapter.parse_webhook(payload) is None


def test_parse_webhook_callback_query() -> None:
    adapter = TelegramAdapter()
    payload: dict[str, Any] = {
        "update_id": 30,
        "callback_query": {
            "id": "cq1",
            "from": {"id": 2},
            "message": {
                "message_id": 9,
                "chat": {"id": -1, "type": "supergroup"},
            },
            "data": "menu:home",
        },
    }
    msg = adapter.parse_webhook(payload)
    assert msg is not None
    assert msg.text == "menu:home"
    assert msg.metadata.get("is_callback") is True
    assert msg.metadata.get("callback_query_id") == "cq1"
    assert msg.metadata.get("callback_data") == "menu:home"


def test_parse_webhook_callback_query_forum_general_thread_id() -> None:
    adapter = TelegramAdapter()
    payload: dict[str, Any] = {
        "update_id": 31,
        "callback_query": {
            "id": "cq-forum",
            "from": {"id": 2},
            "message": {
                "message_id": 9,
                "chat": {"id": -100, "type": "supergroup"},
                "message_thread_id": 1,
            },
            "data": "cfg:section:session",
        },
    }
    msg = adapter.parse_webhook(payload)
    assert msg is not None
    assert msg.metadata.get("topic_id") is None
    assert msg.metadata.get("telegram_thread_id") == 1


def test_parse_webhook_callback_overflow_token_resolves() -> None:
    import json
    import time

    from sevn.storage.migrate import apply_migrations

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    long_data = "plan:" + "x" * 80
    tok = "ds:" + "cd" * 16
    now = int(time.time())
    payload = json.dumps({"v": 1, "callback_data": long_data}, separators=(",", ":"))
    conn.execute(
        (
            "INSERT INTO dispatcher_state (token, kind, user_id, chat_id, topic_id, "
            "payload_json, created_at, expires_at, consumed) VALUES (?, 'callback_overflow', "
            "0, -1, NULL, ?, ?, ?, 0)"
        ),
        (tok, payload, now, now + 3600),
    )
    conn.commit()
    adapter = TelegramAdapter(config=TelegramConfig(bot_token=""), sqlite_conn=conn)
    payload_upd: dict[str, Any] = {
        "update_id": 31,
        "callback_query": {
            "id": "cq2",
            "from": {"id": 2},
            "message": {
                "message_id": 9,
                "chat": {"id": -1, "type": "supergroup"},
            },
            "data": tok,
        },
    }
    msg = adapter.parse_webhook(payload_upd)
    assert msg is not None
    assert msg.text == long_data
    assert msg.metadata.get("callback_data") == long_data


def test_parse_webhook_photo_highest_resolution() -> None:
    adapter = TelegramAdapter()
    payload: dict[str, Any] = {
        "update_id": 40,
        "message": {
            "message_id": 1,
            "from": {"id": 1},
            "chat": {"id": 1, "type": "private"},
            "photo": [
                {"file_id": "small", "width": 1, "height": 1},
                {"file_id": "big", "width": 100, "height": 100},
            ],
            "caption": "pic",
        },
    }
    msg = adapter.parse_webhook(payload)
    assert msg is not None
    assert msg.attachments
    assert msg.attachments[0]["file_id"] == "big"
    assert msg.attachments[0]["type"] == "photo"


def test_parse_webhook_suppresses_bot_self_reply_quote() -> None:
    cfg = TelegramConfig(bot_token="", bot_user_id=777)
    adapter = TelegramAdapter(config=cfg)
    payload: dict[str, Any] = {
        "update_id": 70,
        "message": {
            "message_id": 2,
            "from": {"id": 1},
            "chat": {"id": 1, "type": "private"},
            "text": "follow-up",
            "reply_to_message": {
                "message_id": 1,
                "from": {"id": 777, "is_bot": True, "first_name": "Sevn"},
                "text": "prior bot output",
            },
        },
    }
    msg = adapter.parse_webhook(payload)
    assert msg is not None
    assert msg.metadata.get("reply_to_quote") is None
    assert msg.metadata.get("reply_to_message_id") == 1
    assert msg.text == "follow-up"


def test_parse_webhook_keeps_other_user_quote() -> None:
    cfg = TelegramConfig(bot_token="", bot_user_id=777)
    adapter = TelegramAdapter(config=cfg)
    payload: dict[str, Any] = {
        "update_id": 71,
        "message": {
            "message_id": 3,
            "from": {"id": 1},
            "chat": {"id": -100, "type": "supergroup"},
            "text": "replying to alice",
            "reply_to_message": {
                "message_id": 2,
                "from": {"id": 42, "first_name": "Alice"},
                "text": "alice said this",
            },
        },
    }
    msg = adapter.parse_webhook(payload)
    assert msg is not None
    q = msg.metadata.get("reply_to_quote")
    assert isinstance(q, str)
    assert "alice said this" in q
    assert msg.metadata.get("reply_to_message_id") == 2


def test_parse_webhook_reply_to_quote_not_truncated() -> None:
    adapter = TelegramAdapter()
    inner = "Z" * 500
    payload: dict[str, Any] = {
        "update_id": 50,
        "message": {
            "message_id": 2,
            "from": {"id": 1},
            "chat": {"id": 1, "type": "private"},
            "text": "tail",
            "reply_to_message": {
                "message_id": 1,
                "from": {"id": 2, "first_name": "Sam"},
                "text": inner,
            },
        },
    }
    msg = adapter.parse_webhook(payload)
    assert msg is not None
    q = msg.metadata.get("reply_to_quote")
    assert isinstance(q, str)
    assert inner in q
    assert msg.text == "tail"


def test_forum_topic_created_persists_name() -> None:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(
        """CREATE TABLE telegram_topic_names (
        chat_id INTEGER NOT NULL,
        topic_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (chat_id, topic_id)
    )""",
    )
    adapter = TelegramAdapter(config=TelegramConfig(bot_token=""), sqlite_conn=conn)
    payload: dict[str, Any] = {
        "update_id": 60,
        "message": {
            "message_id": 1,
            "from": {"id": 1},
            "chat": {"id": -55, "type": "supergroup"},
            "message_thread_id": 0,
            "forum_topic_created": {"name": "Infra"},
        },
    }
    assert adapter.parse_webhook(payload) is None
    row = conn.execute(
        "SELECT name FROM telegram_topic_names WHERE chat_id = ? AND topic_id = ?",
        (-55, 0),
    ).fetchone()
    assert row is not None
    assert row[0] == "Infra"
    conn.close()


def test_format_reply_quote_skips_forum_stub() -> None:
    stub = {"message_id": 1, "forum_topic_created": {"name": "T"}}
    assert format_reply_quote(stub) is None


def test_format_reply_quote_normalizes_markdown_v2_escapes() -> None:
    """Backslash-escapes that survive ``reply_to_message.text`` are stripped.

    Covers transcript-review item #13: when the bot's outbound applies
    ``_markdown_escape`` and the user replies to that message, Telegram echoes the
    escaped form back. The quote must surface the original text to the LLM.
    """
    reply = {
        "from": {"first_name": "Alex"},
        "message_id": 1,
        "text": r"name\=value \| flag\>x \(grp\)",
    }
    out = format_reply_quote(reply)
    assert out is not None
    assert "name=value | flag>x (grp)" in out
    # Bare backslashes (not in the escape set) should be left alone.
    assert "\\n" not in out  # the literal escape sequence wasn't introduced


def test_format_reply_quote_leaves_normal_punctuation_alone() -> None:
    """Body without escape backslashes passes through unchanged."""
    reply = {
        "from": {"first_name": "Alex"},
        "message_id": 2,
        "text": "What is 838?",
    }
    out = format_reply_quote(reply)
    assert out is not None
    assert "What is 838?" in out


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"update_id": 1, "message": "not-a-dict"},
        {"update_id": 2, "message": {"text": "hi"}},
        {"update_id": 3, "message": {"from": {"id": 1}, "text": ""}},
        {"update_id": 4, "message": {"from": {"id": 1}, "text": "   "}},
        {"update_id": 5, "message": {"from": {}, "text": "x"}},
    ],
)
def test_parse_webhook_malformed_or_empty_returns_none(payload: dict[str, Any]) -> None:
    assert TelegramAdapter().parse_webhook(payload) is None
