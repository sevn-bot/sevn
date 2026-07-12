"""Deep-link ``/start`` prefix tests (`plan/control-surface-wave-plan.md` Wave 3)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.channels.telegram import TelegramAdapter
from sevn.config.workspace_config import (
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media_store import MediaStore
from sevn.gateway.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.execute("PRAGMA foreign_keys=ON")
    apply_migrations(c)
    return c


class _CapTelegram(TelegramAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[str] = []

    async def send(self, message: Any) -> list[str]:
        self.sent.append(message.text)
        return ["1"]


@pytest.mark.asyncio
async def test_start_onb_prefix_welcome(tmp_path: Path) -> None:
    root = tmp_path / "w"
    root.mkdir()
    ws = WorkspaceConfig(
        schema_version=1,
        security=SecurityWorkspaceConfig(scanner=SecurityScannerSubConfig(heuristic_only=True)),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    conn = _conn()
    cap = _CapTelegram()
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        run_turn=AsyncMock(),
    )
    router.register_adapter(cap)
    layout = WorkspaceLayout(root / "sevn.json", root)
    layout.sevn_json_path.write_text(
        '{"schema_version":1,"workspace_root":".","gateway":{"host":"127.0.0.1","port":3001,"queue_mode":"cancel","token":"${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    build_agent_run_turn(router, conn, ws, layout, NullTraceSink())
    await router.route_incoming(
        IncomingMessage(
            channel="telegram",
            user_id="1",
            text="/start",
            metadata={"start_deep_link": "onb_abc123"},
        ),
    )
    assert cap.sent
    assert "Onboarding link received" in cap.sent[0]


@pytest.mark.asyncio
async def test_start_short_prefix_names_shortcut(tmp_path: Path) -> None:
    root = tmp_path / "w"
    root.mkdir()
    from sevn.gateway.commands.shortcuts_store import add_shortcut

    add_shortcut(
        root,
        {"name": "standup", "description": "Daily", "type": "prompt", "payload": {}},
    )
    ws = WorkspaceConfig(
        schema_version=1,
        security=SecurityWorkspaceConfig(scanner=SecurityScannerSubConfig(heuristic_only=True)),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    conn = _conn()
    cap = _CapTelegram()
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        run_turn=AsyncMock(),
    )
    router.register_adapter(cap)
    layout = WorkspaceLayout(root / "sevn.json", root)
    layout.sevn_json_path.write_text(
        '{"schema_version":1,"workspace_root":".","gateway":{"host":"127.0.0.1","port":3001,"queue_mode":"cancel","token":"${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    build_agent_run_turn(router, conn, ws, layout, NullTraceSink())
    await router.route_incoming(
        IncomingMessage(
            channel="telegram",
            user_id="1",
            text="/start",
            metadata={"start_deep_link": "short_standup", "chat_id": 1},
        ),
    )
    assert any("/standup" in t for t in cap.sent)
