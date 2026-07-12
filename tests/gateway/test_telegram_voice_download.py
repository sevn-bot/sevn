"""Telegram voice download + inbound STT wiring (`voice-bidirectional` W1)."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.channels.telegram import TelegramAdapter
from sevn.config.defaults import VOICE_INBOUND_TRANSCRIPT_PREFIX
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
from sevn.security.llm_guard_scanner import LLMGuardScanner, ScanResult, ScanVerdict
from sevn.storage.migrate import apply_migrations
from sevn.voice.backends import TranscriptionResult
from sevn.voice.stt import SpeechToTextPipeline


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.execute("PRAGMA foreign_keys=ON")
    apply_migrations(c)
    return c


class _FakeSTT:
    id = "fake_stt"

    async def is_available(self) -> bool:
        return True

    async def transcribe(
        self,
        *,
        audio_path: Path,
        mime_type: str | None,
        duration_s: float | None,
        locale: str | None = None,
    ) -> TranscriptionResult:
        _ = mime_type, duration_s, locale
        assert audio_path.is_file()
        return TranscriptionResult(text="hello operator", provider=self.id, confidence=0.9)


class _TelegramWithDownload(TelegramAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.download_calls: list[str] = []

    async def download_attachment(
        self,
        file_id: str,
        *,
        dest_dir: Path,
        attachment_type: str = "voice",
        suggested_name: str | None = None,
    ) -> Path:
        _ = attachment_type, suggested_name
        self.download_calls.append(file_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / f"voice-{file_id}.ogg"
        path.write_bytes(b"fake-audio")
        return path


@pytest.mark.asyncio
async def test_telegram_voice_download_then_stt(tmp_path: Path, monkeypatch: Any) -> None:
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
    scanned: list[str] = []
    try:
        sessions = SessionManager(conn)
        media = MediaStore(conn, root)
        scanner = LLMGuardScanner(root, ws)
        adapter = _TelegramWithDownload()
        stt = SpeechToTextPipeline(
            [_FakeSTT()],
            stt_confidence_reprompt_threshold=0.7,
            trace=NullTraceSink(),
        )

        async def scan(
            _self: LLMGuardScanner,
            *,
            text: str,
            channel: str,
            user_id: str,
            actor_is_owner: bool,
            source: str,
        ) -> ScanResult:
            scanned.append(text)
            _ = channel, user_id, actor_is_owner, source
            return ScanResult(
                verdict=ScanVerdict.allow,
                reasons=(),
                scores={},
                provider_used=None,
                details={},
            )

        monkeypatch.setattr(LLMGuardScanner, "scan_inbound", scan)
        turn_calls: list[tuple[str, str]] = []

        async def _run_turn(session_id: str, correlation_id: str) -> None:
            turn_calls.append((session_id, correlation_id))

        router = ChannelRouter(
            workspace=ws,
            content_root=root,
            sessions=sessions,
            dispatcher=CommandDispatcher(),
            scanner=scanner,
            trace=NullTraceSink(),
            rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
            media=media,
            run_turn=_run_turn,
            stt_pipeline=stt,
        )
        router.register_adapter(adapter)
        msg = IncomingMessage(
            channel="telegram",
            user_id="42",
            text="[voice]",
            attachments=[{"type": "voice", "file_id": "fid-123", "duration_s": 2.0}],
            metadata={"chat_id": 42},
        )
        await router.route_incoming(msg)
        sid_row = conn.execute("SELECT session_id FROM gateway_sessions").fetchone()
        assert sid_row is not None
        sid = sid_row[0]
        for _ in range(50):
            if turn_calls:
                break
            await asyncio.sleep(0.02)
        assert adapter.download_calls == ["fid-123"]
        sid = sid_row[0]
        audio_path = root / "channel_files" / sid / "voice-fid-123.ogg"
        assert audio_path.is_file()
        assert any(VOICE_INBOUND_TRANSCRIPT_PREFIX in line for line in scanned)
        assert "hello operator" in scanned[0]
        assert len(turn_calls) == 1
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()
