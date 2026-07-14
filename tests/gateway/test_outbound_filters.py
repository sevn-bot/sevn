"""Outbound stream hygiene + trace (`specs/17-gateway.md` §4.4, §7)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from sevn.config.workspace_config import (
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.channel_router import ChannelRouter, OutgoingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager, latest_messages
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations


class _ListSink:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.execute("PRAGMA foreign_keys=ON")
    apply_migrations(c)
    return c


@pytest.mark.asyncio
async def test_route_outgoing_strips_think_and_osc(tmp_path: Path) -> None:
    root = tmp_path / "w"
    root.mkdir()
    ws = WorkspaceConfig(
        schema_version=1,
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    conn = _conn()
    try:
        sessions = SessionManager(conn)
        media = MediaStore(conn, root)
        scanner = LLMGuardScanner(root, ws)
        sink = _ListSink()
        router = ChannelRouter(
            workspace=ws,
            content_root=root,
            sessions=sessions,
            dispatcher=CommandDispatcher(),
            scanner=scanner,
            trace=sink,
            rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
            media=media,
        )
        from sevn.channels.telegram import TelegramAdapter

        router.register_adapter(TelegramAdapter())
        await sessions.ensure_session(scope_key="telegram:1", channel="telegram", user_id="1")
        sid = str(
            conn.execute(
                "SELECT session_id FROM gateway_sessions WHERE scope_key = ?",
                ("telegram:1",),
            ).fetchone()[0],
        )
        dirty = "Hello <think>z</think> world\x1b]8;;https://x.example\x07 tail"
        await router.route_outgoing(
            OutgoingMessage(channel="telegram", user_id="1", text=dirty, session_id=sid),
        )
        rows = latest_messages(conn, sid)
        assistant = [r for r in rows if r["role"] == "assistant"][-1]
        assert "<think" not in assistant["content"].lower()
        assert "\x1b]" not in assistant["content"]
        assert "Hello " in assistant["content"]
        assert "world" in assistant["content"]
        kinds = [e.kind for e in sink.events]
        assert "gateway.outgoing.filtered" in kinds
    finally:
        conn.close()
