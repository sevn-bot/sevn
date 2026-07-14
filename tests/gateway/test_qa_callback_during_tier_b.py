"""Wave B2 — qa-feedback ack within 4 s while tier-B is in flight."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.channels.telegram import TelegramAdapter
from sevn.config.workspace_config import WorkspaceConfig, parse_workspace_config
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.gateway.util.strings import QA_LOGGED_FEEDBACK_V1
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


class _CaptureTelegram(TelegramAdapter):
    """Records ``answerCallbackQuery`` calls for timing assertions."""

    def __init__(self) -> None:
        super().__init__(resolved_bot_token="test-token")
        self.answered: list[tuple[float, str, str]] = []

    async def answer_callback(self, callback_query_id: str, *, text: str = "") -> None:
        self.answered.append((time.monotonic(), callback_query_id, text))

    async def send(self, message: Any) -> list[str]:
        _ = message
        return ["1"]

    async def send_chat_action(self, **kwargs: Any) -> None:
        _ = kwargs


def _router_bundle(
    tmp_path: Path, conn: sqlite3.Connection, *, telegram: _CaptureTelegram
) -> tuple[ChannelRouter, WorkspaceConfig, WorkspaceLayout]:
    root = tmp_path / "w"
    root.mkdir()
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {"group_scope": "all", "relax_greeting_lists": False},
            "providers": {"tier_default": {"triager": "stub/model", "B": "stub/tier-b"}},
            "permissions": {"scope_narrowing": {"enabled": False}},
            "security": {"scanner": {"heuristic_only": True}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    layout = WorkspaceLayout(root / "sevn.json", root)
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
    router.register_adapter(telegram)
    build_agent_run_turn(router, conn, ws, layout, NullTraceSink())
    return router, ws, layout


@pytest.mark.asyncio
async def test_qa_down_acks_within_four_seconds_during_tier_b(tmp_path: Path) -> None:
    """``qa:*:down`` answers the callback before tier-B completes; persists feedback."""
    conn = _memory_conn()
    tg = _CaptureTelegram()
    router, _ws, _layout = _router_bundle(tmp_path, conn, telegram=tg)
    tier_b_started = asyncio.Event()
    tier_b_release = asyncio.Event()

    async def slow_run_turn(_sid: str, _cid: str) -> None:
        tier_b_started.set()
        await tier_b_release.wait()

    router._run_turn = slow_run_turn
    session_id = await router._sessions.ensure_session(
        scope_key="telegram:owner",
        channel="telegram",
        user_id="owner",
    )
    assistant_row = await router._sessions.add_message(
        session_id,
        role="assistant",
        kind="message",
        content="answer",
        visible_to_llm=1,
        status="sent",
        turn_id="t-test",
    )
    conn.execute(
        "UPDATE gateway_messages SET platform_message_id = ?, platform_chat_id = ? WHERE id = ?",
        ("200", "9", assistant_row),
    )
    conn.commit()

    user_msg = IncomingMessage(
        channel="telegram",
        user_id="owner",
        text="hello",
        metadata={"chat_id": 9},
    )
    user_task = asyncio.create_task(router.route_incoming(user_msg))
    await asyncio.wait_for(tier_b_started.wait(), timeout=5.0)

    qa_msg = IncomingMessage(
        channel="telegram",
        user_id="owner",
        text="qa:200:down",
        metadata={
            "callback_data": "qa:200:down",
            "callback_query_id": "cq-tier-b-blocked",
            "is_callback": True,
            "chat_id": 9,
        },
    )
    try:
        t0 = time.monotonic()
        await router.route_incoming(qa_msg)
        elapsed = time.monotonic() - t0
        assert elapsed < 4.0
        assert len(tg.answered) == 1
        assert tg.answered[0][1] == "cq-tier-b-blocked"
        assert tg.answered[0][2] == QA_LOGGED_FEEDBACK_V1

        row = conn.execute("SELECT kind FROM feedback_events").fetchone()
        assert row is not None
        assert row[0] == "thumbs_down"

        tier_b_release.set()
        await asyncio.wait_for(user_task, timeout=5.0)
    finally:
        tier_b_release.set()
        await router.session_manager.drain()
        conn.close()
