"""CommandDispatcher bypass + callback namespace (`specs/17-gateway.md` §2.4, §10.4)."""

from __future__ import annotations

import asyncio
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
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media_store import MediaStore
from sevn.gateway.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.gateway.steer_store import SessionSteerStore
from sevn.gateway.strings import STEER_NOT_AVAILABLE_V1, STEER_USAGE_V1
from sevn.security.llm_guard_scanner import LLMGuardScanner, ScanResult, ScanVerdict
from sevn.storage.migrate import apply_migrations


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.execute("PRAGMA foreign_keys=ON")
    apply_migrations(c)
    return c


class _CaptureTelegram(TelegramAdapter):
    """Records ``send`` text for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.sent_texts: list[str] = []

    async def send(self, message: Any) -> list[str]:
        self.sent_texts.append(message.text)
        return await super().send(message)


@pytest.mark.asyncio
async def test_help_bypass_skips_scanner_and_run_turn(tmp_path: Path, monkeypatch: Any) -> None:
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
    router: ChannelRouter | None = None
    try:
        sessions = SessionManager(conn)
        media = MediaStore(conn, root)
        scanner = LLMGuardScanner(root, ws)
        run_turn = AsyncMock()

        async def boom_scan(
            _self: LLMGuardScanner,
            *,
            text: str,
            channel: str,
            user_id: str,
            actor_is_owner: bool,
            source: str,
        ) -> ScanResult:
            _ = text, channel, user_id, actor_is_owner, source
            raise AssertionError("scanner must not run on dispatcher hit")

        monkeypatch.setattr(LLMGuardScanner, "scan_inbound", boom_scan)
        router = ChannelRouter(
            workspace=ws,
            content_root=root,
            sessions=sessions,
            dispatcher=CommandDispatcher(),
            scanner=scanner,
            trace=NullTraceSink(),
            rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
            media=media,
            run_turn=run_turn,
        )
        await router.route_incoming(
            IncomingMessage(channel="telegram", user_id="owner", text="/help"),
        )
        run_turn.assert_not_called()
        n = int(
            conn.execute(
                "SELECT COUNT(*) FROM gateway_messages WHERE kind = 'command'",
            ).fetchone()[0],
        )
        assert n == 1
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_topic_with_args_hits_scanner_not_dispatcher(
    tmp_path: Path, monkeypatch: Any
) -> None:
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
    router: ChannelRouter | None = None
    try:
        sessions = SessionManager(conn)
        media = MediaStore(conn, root)
        scanner = LLMGuardScanner(root, ws)
        calls: list[str] = []

        async def scan(
            _self: LLMGuardScanner,
            *,
            text: str,
            channel: str,
            user_id: str,
            actor_is_owner: bool,
            source: str,
        ) -> ScanResult:
            calls.append(text)
            _ = channel, user_id, actor_is_owner, source
            return ScanResult(
                verdict=ScanVerdict.allow,
                reasons=(),
                scores={},
                provider_used=None,
                details={},
            )

        monkeypatch.setattr(LLMGuardScanner, "scan_inbound", scan)
        run_turn = AsyncMock()
        router = ChannelRouter(
            workspace=ws,
            content_root=root,
            sessions=sessions,
            dispatcher=CommandDispatcher(),
            scanner=scanner,
            trace=NullTraceSink(),
            rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
            media=media,
            run_turn=run_turn,
        )
        await router.route_incoming(
            IncomingMessage(channel="telegram", user_id="u", text="/topic free text"),
        )
        await asyncio.sleep(0.1)
        assert calls == ["/topic free text"]
        run_turn.assert_awaited()
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_callback_namespace_menu_bypass(tmp_path: Path, monkeypatch: Any) -> None:
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
    router: ChannelRouter | None = None
    try:
        sessions = SessionManager(conn)
        media = MediaStore(conn, root)
        scanner = LLMGuardScanner(root, ws)
        run_turn = AsyncMock()

        async def boom_scan(
            _self: LLMGuardScanner,
            *,
            text: str,
            channel: str,
            user_id: str,
            actor_is_owner: bool,
            source: str,
        ) -> ScanResult:
            _ = text, channel, user_id, actor_is_owner, source
            raise AssertionError("scanner must not run on callback stub")

        monkeypatch.setattr(LLMGuardScanner, "scan_inbound", boom_scan)
        cap = _CaptureTelegram()
        router = ChannelRouter(
            workspace=ws,
            content_root=root,
            sessions=sessions,
            dispatcher=CommandDispatcher(),
            scanner=scanner,
            trace=NullTraceSink(),
            rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
            media=media,
            run_turn=run_turn,
        )
        router.register_adapter(cap)
        await router.route_incoming(
            IncomingMessage(
                channel="telegram",
                user_id="u",
                text="",
                metadata={"callback_data": "menu:home"},
            ),
        )
        run_turn.assert_not_called()
        assert cap.sent_texts == []
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()


@pytest.mark.parametrize(
    "text",
    ["/start", "/new", "/status", "/stop", "/config", "/voice", "/model"],
)
def test_option_b_commands_registered(text: str) -> None:
    dispatcher = CommandDispatcher()
    assert dispatcher.try_dispatch(
        IncomingMessage(channel="telegram", user_id="1", text=text),
    )


def test_unknown_command_not_dispatched() -> None:
    dispatcher = CommandDispatcher()
    assert not dispatcher.try_dispatch(
        IncomingMessage(channel="telegram", user_id="1", text="/not-a-command"),
    )


@pytest.mark.asyncio
async def test_steer_bypass_without_store_sends_legacy_copy(
    tmp_path: Path, monkeypatch: Any
) -> None:
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
    router: ChannelRouter | None = None
    try:
        sessions = SessionManager(conn)
        media = MediaStore(conn, root)
        scanner = LLMGuardScanner(root, ws)
        run_turn = AsyncMock()

        async def boom_scan(
            _self: LLMGuardScanner,
            *,
            text: str,
            channel: str,
            user_id: str,
            actor_is_owner: bool,
            source: str,
        ) -> ScanResult:
            _ = text, channel, user_id, actor_is_owner, source
            raise AssertionError("scanner must not run on /steer bypass")

        monkeypatch.setattr(LLMGuardScanner, "scan_inbound", boom_scan)
        cap = _CaptureTelegram()
        router = ChannelRouter(
            workspace=ws,
            content_root=root,
            sessions=sessions,
            dispatcher=CommandDispatcher(),
            scanner=scanner,
            trace=NullTraceSink(),
            rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
            media=media,
            run_turn=run_turn,
            owner_user_ids=frozenset({"owner"}),
        )
        router.register_adapter(cap)
        await router.route_incoming(
            IncomingMessage(channel="telegram", user_id="owner", text="/steer"),
        )
        run_turn.assert_not_called()
        assert cap.sent_texts == [STEER_NOT_AVAILABLE_V1]
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_steer_bypass_with_store_owner_gets_usage(tmp_path: Path, monkeypatch: Any) -> None:
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
    router: ChannelRouter | None = None
    try:
        sessions = SessionManager(conn)
        media = MediaStore(conn, root)
        scanner = LLMGuardScanner(root, ws)
        run_turn = AsyncMock()
        store = SessionSteerStore(max_pending=4)

        async def boom_scan(
            _self: LLMGuardScanner,
            *,
            text: str,
            channel: str,
            user_id: str,
            actor_is_owner: bool,
            source: str,
        ) -> ScanResult:
            _ = text, channel, user_id, actor_is_owner, source
            raise AssertionError("scanner must not run on /steer bypass")

        monkeypatch.setattr(LLMGuardScanner, "scan_inbound", boom_scan)
        cap = _CaptureTelegram()
        router = ChannelRouter(
            workspace=ws,
            content_root=root,
            sessions=sessions,
            dispatcher=CommandDispatcher(steer_store=store),
            scanner=scanner,
            trace=NullTraceSink(),
            rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
            media=media,
            run_turn=run_turn,
            owner_user_ids=frozenset({"owner"}),
            steer_store=store,
        )
        router.register_adapter(cap)
        await router.route_incoming(
            IncomingMessage(channel="telegram", user_id="owner", text="/steer"),
        )
        run_turn.assert_not_called()
        assert cap.sent_texts == [STEER_USAGE_V1]
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()
