"""ChannelRouter integration tests (in-memory SQLite)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

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
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.gateway.util.strings import BLOCKED_INBOUND_USER_MESSAGE
from sevn.security.llm_guard_scanner import LLMGuardScanner, ScanResult, ScanVerdict
from sevn.storage.migrate import apply_migrations


class _CaptureTelegram(TelegramAdapter):
    """Records outbound ``send`` text."""

    def __init__(self) -> None:
        super().__init__()
        self.sent_texts: list[str] = []

    async def send(self, message: Any) -> list[str]:
        self.sent_texts.append(message.text)
        return await super().send(message)


def _router_bundle(
    content_root: Path,
    conn: sqlite3.Connection,
    *,
    rate: TokenBucketLimiter | None = None,
) -> ChannelRouter:
    ws = WorkspaceConfig(
        schema_version=1,
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    sessions = SessionManager(conn)
    media = MediaStore(conn, content_root)
    lim = rate or TokenBucketLimiter(capacity=50.0, refill_per_second=25.0)
    scanner = LLMGuardScanner(content_root, ws)
    return ChannelRouter(
        workspace=ws,
        content_root=content_root,
        sessions=sessions,
        dispatcher=CommandDispatcher(),
        scanner=scanner,
        trace=NullTraceSink(),
        rate=lim,
        media=media,
    )


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


@pytest.mark.asyncio
async def test_rate_limit_blocks_burst(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    async def _stub(
        _self: LLMGuardScanner,
        *,
        text: str,
        channel: str,
        user_id: str,
        actor_is_owner: bool,
        source: str,
    ) -> ScanResult:
        _ = text, channel, user_id, actor_is_owner, source
        return ScanResult(
            verdict=ScanVerdict.allow,
            reasons=(),
            scores={},
            provider_used=None,
            details={"test": True},
        )

    monkeypatch.setattr(LLMGuardScanner, "scan_inbound", _stub)
    root = tmp_path / "w"
    root.mkdir()
    conn = _memory_conn()
    router: ChannelRouter | None = None
    try:
        rate = TokenBucketLimiter(capacity=1.0, refill_per_second=0.0001)
        router = _router_bundle(root, conn, rate=rate)
        msg = IncomingMessage(channel="telegram", user_id="u1", text="ping")
        await router.route_incoming(msg)
        msg2 = IncomingMessage(channel="telegram", user_id="u1", text="pong")
        await router.route_incoming(msg2)
        cur = conn.execute(
            "SELECT COUNT(*) FROM gateway_messages WHERE kind = 'message'",
        ).fetchone()[0]
        assert int(cur) == 1
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_blocked_path_writes_row(tmp_path: Path) -> None:
    root = tmp_path / "w"
    root.mkdir()
    conn = _memory_conn()
    router: ChannelRouter | None = None
    try:
        cap = _CaptureTelegram()
        router = _router_bundle(root, conn)
        router.register_adapter(cap)
        msg = IncomingMessage(channel="telegram", user_id="u2", text="kill stupid moron")
        await router.route_incoming(msg)
        cur = conn.execute(
            "SELECT COUNT(*) FROM gateway_messages WHERE kind = 'blocked'",
        ).fetchone()[0]
        assert int(cur) >= 1
        assert cap.sent_texts == [BLOCKED_INBOUND_USER_MESSAGE]
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_session_scope_override_splits_sessions(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    async def _stub(
        _self: LLMGuardScanner,
        *,
        text: str,
        channel: str,
        user_id: str,
        actor_is_owner: bool,
        source: str,
    ) -> ScanResult:
        _ = text, channel, user_id, actor_is_owner, source
        return ScanResult(
            verdict=ScanVerdict.allow,
            reasons=(),
            scores={},
            provider_used=None,
            details={},
        )

    monkeypatch.setattr(LLMGuardScanner, "scan_inbound", _stub)
    root = tmp_path / "w"
    root.mkdir()
    conn = _memory_conn()
    router: ChannelRouter | None = None
    try:
        router = _router_bundle(root, conn)
        await router.route_incoming(
            IncomingMessage(
                channel="telegram",
                user_id="same",
                text="dm",
                metadata={"session_scope_override": "telegram:dm:same"},
            ),
        )
        await router.route_incoming(
            IncomingMessage(
                channel="telegram",
                user_id="same",
                text="group",
                metadata={"session_scope_override": "telegram_chat:999"},
            ),
        )
        n = int(conn.execute("SELECT COUNT(*) FROM gateway_sessions").fetchone()[0])
        assert n == 2
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_attachment_data_base64_persisted_under_channel_files(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    async def _stub(
        _self: LLMGuardScanner,
        *,
        text: str,
        channel: str,
        user_id: str,
        actor_is_owner: bool,
        source: str,
    ) -> ScanResult:
        _ = text, channel, user_id, actor_is_owner, source
        return ScanResult(
            verdict=ScanVerdict.allow,
            reasons=(),
            scores={},
            provider_used=None,
            details={},
        )

    monkeypatch.setattr(LLMGuardScanner, "scan_inbound", _stub)
    root = tmp_path / "w"
    root.mkdir()
    conn = _memory_conn()
    router: ChannelRouter | None = None
    try:
        router = _router_bundle(root, conn)
        b64 = "QUJD"
        await router.route_incoming(
            IncomingMessage(
                channel="telegram",
                user_id="att",
                text="with file",
                attachments=[{"filename": "note.bin", "data_base64": b64}],
            ),
        )
        row = conn.execute(
            "SELECT session_id FROM gateway_sessions WHERE scope_key = ?",
            ("telegram:att",),
        ).fetchone()
        assert row is not None
        sid = str(row[0])
        path = root / "channel_files" / sid / "note.bin"
        assert path.is_file()
        assert path.read_bytes() == b"ABC"
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_reply_to_quote_metadata_prefix_persisted(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    async def _stub(
        _self: LLMGuardScanner,
        *,
        text: str,
        channel: str,
        user_id: str,
        actor_is_owner: bool,
        source: str,
    ) -> ScanResult:
        _ = text, channel, user_id, actor_is_owner, source
        return ScanResult(
            verdict=ScanVerdict.allow,
            reasons=(),
            scores={},
            provider_used=None,
            details={},
        )

    monkeypatch.setattr(LLMGuardScanner, "scan_inbound", _stub)
    root = tmp_path / "w"
    root.mkdir()
    conn = _memory_conn()
    router: ChannelRouter | None = None
    try:
        router = _router_bundle(root, conn)
        quote = "[Quote]\n" + ("y" * 200) + "\n[/Quote]\n"
        await router.route_incoming(
            IncomingMessage(
                channel="telegram",
                user_id="rq2",
                text="tail",
                metadata={"reply_to_quote": quote},
            ),
        )
        row = conn.execute(
            "SELECT content FROM gateway_messages WHERE session_id IN "
            "(SELECT session_id FROM gateway_sessions WHERE scope_key = ?) "
            "AND kind = 'message' AND role = 'user'",
            ("telegram:rq2",),
        ).fetchone()
        assert row is not None
        body = str(row[0])
        assert body.startswith(quote)
        assert body.endswith("tail")
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_reply_quote_prefix_persisted_untruncated(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    async def _stub(
        _self: LLMGuardScanner,
        *,
        text: str,
        channel: str,
        user_id: str,
        actor_is_owner: bool,
        source: str,
    ) -> ScanResult:
        _ = text, channel, user_id, actor_is_owner, source
        return ScanResult(
            verdict=ScanVerdict.allow,
            reasons=(),
            scores={},
            provider_used=None,
            details={},
        )

    monkeypatch.setattr(LLMGuardScanner, "scan_inbound", _stub)
    root = tmp_path / "w"
    root.mkdir()
    conn = _memory_conn()
    router: ChannelRouter | None = None
    try:
        router = _router_bundle(root, conn)
        quote = "[Quote]\n" + ("x" * 4000) + "\n[/Quote]\n"
        await router.route_incoming(
            IncomingMessage(
                channel="telegram",
                user_id="rq",
                text="tail",
                metadata={"reply_quote": quote},
            ),
        )
        row = conn.execute(
            "SELECT content FROM gateway_messages WHERE session_id IN "
            "(SELECT session_id FROM gateway_sessions WHERE scope_key = ?) "
            "AND kind = 'message' AND role = 'user'",
            ("telegram:rq",),
        ).fetchone()
        assert row is not None
        body = str(row[0])
        assert body.startswith(quote)
        assert body.endswith("tail")
        assert len(body) == len(quote) + len("tail")
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()
