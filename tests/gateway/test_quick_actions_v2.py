"""Wave 4 quick-action bar v2 — toggle semantics + visibility (`specs/18-channel-telegram.md` §10.10)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sevn.config.workspace_config import (
    ChannelsWorkspaceSectionConfig,
    TelegramChannelConfig,
    TelegramQuickActionsConfig,
    WorkspaceConfig,
)
from sevn.gateway.channel_router import IncomingMessage
from sevn.gateway.telegram_quick_actions import (
    QuickActionCallbackHandler,
    build_quick_action_inline_keyboard,
)
from sevn.storage.migrate import apply_migrations


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _ws(*, show_regen: bool = True) -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        channels=ChannelsWorkspaceSectionConfig(
            telegram=TelegramChannelConfig(
                quick_actions=TelegramQuickActionsConfig(show_regen=show_regen),
            ),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


def test_build_keyboard_hides_regen_when_configured() -> None:
    """Per-button hide flag ``show_regen=false`` omits Regen from the row."""
    conn = _memory_conn()
    kb = build_quick_action_inline_keyboard(
        10,
        workspace=_ws(show_regen=False),
        conn=conn,
        user_id="owner",
        gateway_message_id=1,
        platform_chat_id=9,
    )
    row = kb["inline_keyboard"][0]
    labels = [b.get("text") for b in row]
    assert "♻ Regen" not in labels
    assert any(b.get("callback_data") == "qa:10:up" for b in row)
    conn.close()


def test_build_keyboard_five_buttons_with_web_app_tokens() -> None:
    """Share + Feedback ``web_app`` buttons appear when conn mints dispatcher tokens."""
    conn = _memory_conn()
    ws = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        channels=ChannelsWorkspaceSectionConfig(
            telegram=TelegramChannelConfig(
                webhook_url="https://bot.example.com/telegram/webhook",
                quick_actions=TelegramQuickActionsConfig(),
            ),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    kb = build_quick_action_inline_keyboard(
        55,
        workspace=ws,
        conn=conn,
        user_id="owner",
        gateway_message_id=7,
        platform_chat_id=1,
        share_text="answer text",
    )
    row = kb["inline_keyboard"][0]
    assert len(row) == 5
    assert row[3]["text"] == "🔗 Share"
    assert "web_app" in row[3]
    assert row[4]["text"] == "📝 Feedback"
    conn.close()


def test_build_keyboard_omits_webapp_on_http_but_keeps_callbacks() -> None:
    """HTTP gateway base must not attach ``web_app`` buttons (Telegram rejects whole row)."""
    conn = _memory_conn()
    kb = build_quick_action_inline_keyboard(
        55,
        workspace=_ws(),
        conn=conn,
        user_id="owner",
        gateway_message_id=7,
        platform_chat_id=1,
        share_text="answer text",
    )
    row = kb["inline_keyboard"][0]
    assert len(row) == 3
    assert all("web_app" not in btn for btn in row)
    assert any(btn.get("callback_data") == "qa:55:regen" for btn in row)
    conn.close()


def _ws_base(*, webhook_url: str | None = None, **toggles: bool) -> WorkspaceConfig:
    """Workspace whose QA-bar visibility + gateway scheme can be tuned (D6)."""
    return WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        channels=ChannelsWorkspaceSectionConfig(
            telegram=TelegramChannelConfig(
                webhook_url=webhook_url,
                quick_actions=TelegramQuickActionsConfig(**toggles),
            ),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


def test_d6_http_base_keeps_callback_thumbs_drops_web_app() -> None:
    """W5/D6: a plain-HTTP gateway base still ships callback thumbs; no ``web_app`` buttons."""
    conn = _memory_conn()
    kb = build_quick_action_inline_keyboard(
        70,
        # No webhook_url → resolve_webapp_public_base falls back to http://… (non-HTTPS).
        workspace=_ws_base(),
        conn=conn,
        user_id="owner",
        gateway_message_id=3,
        platform_chat_id=9,
        share_text="answer",
    )
    row = kb["inline_keyboard"][0]
    callbacks = [b.get("callback_data") for b in row if "callback_data" in b]
    assert "qa:70:regen" in callbacks
    assert "qa:70:up" in callbacks
    assert "qa:70:down" in callbacks
    assert all("web_app" not in b for b in row)
    conn.close()


def test_d6_https_base_adds_web_app_share_and_feedback() -> None:
    """W5/D6: an HTTPS gateway base ships callback thumbs PLUS ``web_app`` Share/Feedback."""
    conn = _memory_conn()
    kb = build_quick_action_inline_keyboard(
        71,
        workspace=_ws_base(webhook_url="https://bot.example.com/telegram/webhook"),
        conn=conn,
        user_id="owner",
        gateway_message_id=4,
        platform_chat_id=9,
        share_text="answer",
    )
    row = kb["inline_keyboard"][0]
    callbacks = [b.get("callback_data") for b in row if "callback_data" in b]
    assert callbacks == ["qa:71:regen", "qa:71:up", "qa:71:down"]
    web_app_labels = [b["text"] for b in row if "web_app" in b]
    assert web_app_labels == ["🔗 Share", "📝 Feedback"]
    conn.close()


def test_d6_thumb_toggles_respected_independent_of_scheme() -> None:
    """W5.3/D6: ``show_*`` toggles gate buttons regardless of the gateway scheme."""
    conn = _memory_conn()
    kb = build_quick_action_inline_keyboard(
        72,
        workspace=_ws_base(
            webhook_url="https://bot.example.com/telegram/webhook",
            show_thumbs_down=False,
            show_share=False,
        ),
        conn=conn,
        user_id="owner",
        gateway_message_id=5,
        platform_chat_id=9,
        share_text="answer",
    )
    row = kb["inline_keyboard"][0]
    labels = [b.get("text") for b in row]
    assert "👎" not in labels  # show_thumbs_down=False
    assert "🔗 Share" not in labels  # show_share=False
    assert "👍" in labels  # thumbs_up still on
    assert "📝 Feedback" in labels  # feedback still on (HTTPS)
    conn.close()


@pytest.mark.asyncio
async def test_thumbs_up_twice_clears(tmp_path: Path) -> None:
    """Second 👍 tap inserts ``thumbs_up_clear``."""
    conn = _memory_conn()
    handler = QuickActionCallbackHandler.__new__(QuickActionCallbackHandler)
    handler._conn = conn
    handler._router = None  # type: ignore[assignment]
    session_id = "s1"
    conn.execute(
        "INSERT INTO gateway_sessions (session_id, channel, scope_key, user_id, created_at, updated_at) "
        "VALUES ('s1', 'telegram', 'telegram:owner', 'owner', datetime('now'), datetime('now'))",
    )
    conn.execute(
        "INSERT INTO gateway_messages (session_id, role, kind, content, visible_to_llm, status, "
        "platform_message_id, platform_chat_id, created_at) "
        "VALUES ('s1', 'assistant', 'message', 'hi', 1, 'sent', '200', '9', datetime('now'))",
    )
    conn.commit()
    msg = IncomingMessage(
        channel="telegram",
        user_id="owner",
        text="qa:200:up",
        metadata={"callback_data": "qa:200:up", "chat_id": 9},
    )
    toast1 = await handler.handle(msg, session_id=session_id, is_owner=True)
    assert toast1 is not None
    row1 = conn.execute("SELECT kind FROM feedback_events ORDER BY created_at").fetchall()
    assert row1[-1][0] == "thumbs_up"
    toast2 = await handler.handle(msg, session_id=session_id, is_owner=True)
    assert toast2 is not None
    row2 = conn.execute("SELECT kind FROM feedback_events ORDER BY created_at").fetchall()
    assert row2[-1][0] == "thumbs_up_clear"
    conn.close()


@pytest.mark.asyncio
async def test_thumbs_up_then_down_switches() -> None:
    """👍 then 👎 emits ``thumbs_switch``."""
    conn = _memory_conn()
    handler = QuickActionCallbackHandler.__new__(QuickActionCallbackHandler)
    handler._conn = conn
    handler._router = None  # type: ignore[assignment]
    session_id = "s1"
    conn.execute(
        "INSERT INTO gateway_sessions (session_id, channel, scope_key, user_id, created_at, updated_at) "
        "VALUES ('s1', 'telegram', 'telegram:owner', 'owner', datetime('now'), datetime('now'))",
    )
    conn.execute(
        "INSERT INTO gateway_messages (session_id, role, kind, content, visible_to_llm, status, "
        "platform_message_id, platform_chat_id, created_at) "
        "VALUES ('s1', 'assistant', 'message', 'hi', 1, 'sent', '201', '9', datetime('now'))",
    )
    conn.commit()
    up = IncomingMessage(
        channel="telegram",
        user_id="owner",
        text="qa:201:up",
        metadata={"callback_data": "qa:201:up", "chat_id": 9},
    )
    down = IncomingMessage(
        channel="telegram",
        user_id="owner",
        text="qa:201:down",
        metadata={"callback_data": "qa:201:down", "chat_id": 9},
    )
    await handler.handle(up, session_id=session_id, is_owner=True)
    await handler.handle(down, session_id=session_id, is_owner=True)
    kinds = [
        r[0]
        for r in conn.execute("SELECT kind FROM feedback_events ORDER BY created_at").fetchall()
    ]
    assert kinds == ["thumbs_up", "thumbs_switch"]
    payload = conn.execute(
        "SELECT payload_json FROM feedback_events WHERE kind = 'thumbs_switch'",
    ).fetchone()
    assert payload is not None
    assert '"from": "up"' in str(payload[0])
    assert '"to": "down"' in str(payload[0])
    conn.close()
