"""``route_outgoing`` rich decision metadata (R4.4)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.channels.telegram import (
    TELEGRAM_RICH_DRAFT_KEY,
    TELEGRAM_STREAMING_ACTIVE_KEY,
    TELEGRAM_USE_RICH_KEY,
    TelegramAdapter,
)
from sevn.channels.telegram_capabilities import RichCapability
from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway.channel_router import ChannelRouter, OutgoingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.gateway.telegram.telegram_quick_actions import GATEWAY_OUTBOUND_PHASE_KEY
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations

_TABLE = "| A | B |\n|---|---|\n| 1 | 2 |\n"


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


class _CaptureTelegram(TelegramAdapter):
    """Records outbound metadata from ``route_outgoing``."""

    def __init__(self) -> None:
        super().__init__(resolved_bot_token="test-token")
        self._rich_capability = RichCapability.CAPABLE
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: Any) -> list[str]:
        md = dict(message.metadata) if isinstance(message.metadata, dict) else {}
        self.sent.append({"text": message.text, "metadata": md})
        return ["100"]

    async def edit_reply_markup(self, **kwargs: Any) -> bool:
        _ = kwargs
        return True


def _router(tmp_path: Path, conn: sqlite3.Connection, tg: _CaptureTelegram) -> ChannelRouter:
    root = tmp_path / "w"
    root.mkdir()
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "channels": {"telegram": {"rich": {"mode": "auto"}}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=10.0, refill_per_second=5.0),
        media=MediaStore(conn, root),
        owner_user_ids=frozenset({"owner"}),
    )
    router.register_adapter(tg)
    return router


@pytest.mark.asyncio
async def test_route_outgoing_sets_use_rich_for_table_reply(tmp_path: Path) -> None:
    conn = _memory_conn()
    tg = _CaptureTelegram()
    router = _router(tmp_path, conn, tg)
    session_id = await router._sessions.ensure_session(
        scope_key="telegram:owner",
        channel="telegram",
        user_id="owner",
    )
    await router.route_outgoing(
        OutgoingMessage(
            channel="telegram",
            user_id="owner",
            text=_TABLE,
            session_id=session_id,
            metadata={"chat_id": 42, GATEWAY_OUTBOUND_PHASE_KEY: "final"},
        ),
    )
    assert tg.sent
    md = tg.sent[0]["metadata"]
    assert md[TELEGRAM_USE_RICH_KEY] is True


@pytest.mark.asyncio
async def test_route_outgoing_plain_text_not_rich(tmp_path: Path) -> None:
    conn = _memory_conn()
    tg = _CaptureTelegram()
    router = _router(tmp_path, conn, tg)
    session_id = await router._sessions.ensure_session(
        scope_key="telegram:owner",
        channel="telegram",
        user_id="owner",
    )
    await router.route_outgoing(
        OutgoingMessage(
            channel="telegram",
            user_id="owner",
            text="hello",
            session_id=session_id,
            metadata={"chat_id": 42, GATEWAY_OUTBOUND_PHASE_KEY: "final"},
        ),
    )
    md = tg.sent[0]["metadata"]
    assert md[TELEGRAM_USE_RICH_KEY] is False


@pytest.mark.asyncio
async def test_route_outgoing_early_phase_sets_streaming_draft(tmp_path: Path) -> None:
    conn = _memory_conn()
    tg = _CaptureTelegram()
    router = _router(tmp_path, conn, tg)
    session_id = await router._sessions.ensure_session(
        scope_key="telegram:owner",
        channel="telegram",
        user_id="owner",
    )
    await router.route_outgoing(
        OutgoingMessage(
            channel="telegram",
            user_id="owner",
            text="…",
            session_id=session_id,
            metadata={"chat_id": 42, GATEWAY_OUTBOUND_PHASE_KEY: "early"},
        ),
    )
    md = tg.sent[0]["metadata"]
    assert md[TELEGRAM_USE_RICH_KEY] is True
    assert md[TELEGRAM_STREAMING_ACTIVE_KEY] is True
    assert md[TELEGRAM_RICH_DRAFT_KEY] is True
