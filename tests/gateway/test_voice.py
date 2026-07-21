"""Gateway voice session override + outbound TTS gating (`voice-bidirectional` W4/W5)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.channels.telegram import TelegramAdapter
from sevn.config.workspace_config import VoiceConfig, WorkspaceConfig
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage, OutgoingMessage
from sevn.gateway.commands.core_commands import CoreCommandHandler, _normalise_tts_voice_code
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.config_io.workspace_config_io import load_raw_sevn_json
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.onboarding.web_app import _get_nested
from sevn.security.llm_guard_scanner import LLMGuardScanner, ScanResult
from sevn.storage.migrate import apply_migrations
from sevn.voice.factory import resolve_effective_tts_mode
from sevn.voice.tts import TextToSpeechPipeline
from sevn.workspace.layout import WorkspaceLayout


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.execute("PRAGMA foreign_keys=ON")
    apply_migrations(c)
    return c


class _CaptureAdapter:
    name = "telegram"
    channel = "telegram"

    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send(self, message: OutgoingMessage) -> list[str]:
        self.sent.append(message)
        return ["1"]


class _OkTTS:
    id = "mock_tts"

    async def is_available(self) -> bool:
        return True

    async def synthesize(
        self,
        *,
        text: str,
        voice_id: str | None,
        out_path: Path,
    ) -> None:
        _ = voice_id
        out_path.write_bytes(b"audio")


@pytest.mark.asyncio
async def test_session_tts_override_independent(tmp_path: Path) -> None:
    conn = _conn()
    conn.execute(
        """
        INSERT INTO gateway_sessions(session_id, scope_key, channel, user_id, created_at, updated_at)
        VALUES (?,?,?,?,?,?)
        """,
        ("s1", "k1", "telegram", "1", "t", "t"),
    )
    conn.execute(
        """
        INSERT INTO gateway_sessions(session_id, scope_key, channel, user_id, created_at, updated_at)
        VALUES (?,?,?,?,?,?)
        """,
        ("s2", "k2", "telegram", "2", "t", "t"),
    )
    conn.commit()
    sm = SessionManager(conn)
    sm.set_tts_mode_override("s1", "all")
    assert (
        resolve_effective_tts_mode(
            global_mode="off", session_override=sm.get_tts_mode_override("s1")
        )
        == "all"
    )
    assert (
        resolve_effective_tts_mode(
            global_mode="off", session_override=sm.get_tts_mode_override("s2")
        )
        == "off"
    )
    conn.close()


@pytest.mark.asyncio
async def test_route_outgoing_uses_session_override_and_voice_note_trigger(tmp_path: Path) -> None:
    root = tmp_path / "w"
    root.mkdir()
    sevn_json = root / "sevn.json"
    sevn_json.write_text('{"schema_version":1,"workspace_root":"."}', encoding="utf-8")
    ws = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        voice=VoiceConfig(tts_mode="when_asked", voice_trigger_keywords=["never-match"]),
        gateway={"token": "x"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, ws)
    conn = _conn()
    conn.execute(
        """
        INSERT INTO gateway_sessions(session_id, scope_key, channel, user_id, created_at, updated_at)
        VALUES (?,?,?,?,?,?)
        """,
        ("sess", "scope", "telegram", "1", "t", "t"),
    )
    conn.commit()
    router: ChannelRouter | None = None
    try:
        sessions = SessionManager(conn)
        sessions.set_tts_mode_override("sess", "when_asked")
        media = MediaStore(conn, root)
        scanner = LLMGuardScanner(root, ws)
        tts_dir = root / "out" / "audio"
        tts = TextToSpeechPipeline(
            [_OkTTS()],
            voice_trigger_keywords=("never-match",),
            trace=NullTraceSink(),
            tts_output_dir=tts_dir,
        )
        router = ChannelRouter(
            workspace=ws,
            content_root=layout.content_root,
            sessions=sessions,
            dispatcher=CommandDispatcher(),
            scanner=scanner,
            trace=NullTraceSink(),
            rate=TokenBucketLimiter(capacity=10.0, refill_per_second=10.0),
            media=media,
            run_turn=AsyncMock(),
            tts_pipeline=tts,
        )
        adapter = _CaptureAdapter()
        router.register_adapter(adapter)
        router._session_inbound_voice_flag["sess"] = True
        await router.route_outgoing(
            OutgoingMessage(
                channel="telegram",
                user_id="1",
                text="reply text",
                session_id="sess",
                metadata={"chat_id": 1},
            ),
        )
        assert adapter.sent
        assert adapter.sent[0].metadata.get("tts_audio_path")
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("F3", "F3"),
        ("f3", "F3"),
        ("M1", "M1"),
        ("af_heart", "af_heart"),
        ("AF_Heart", "af_heart"),
        ("F9", None),
        ("on", None),
    ],
)
def test_normalise_tts_voice_code(raw: str, expected: str | None) -> None:
    assert _normalise_tts_voice_code(raw) == expected


def test_handle_voice_persists_supertonic_and_kokoro_codes(tmp_path: Path) -> None:
    """``/voice`` persists Supertonic uppercase + Kokoro lowercase; rejects unknowns."""
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps({"schema_version": 1, "gateway": {"token": "t"}, "voice": {}}),
        encoding="utf-8",
    )
    handler = CoreCommandHandler.__new__(CoreCommandHandler)
    handler._workspace = WorkspaceConfig.minimal()
    handler._sevn_json = sevn_json
    handler._sessions = type("S", (), {"set_tts_mode_override": lambda *_a, **_k: None})()
    handler._reload_workspace = lambda: None  # type: ignore[method-assign]

    assert "F3" in handler._handle_voice("f3", session_id="s")
    assert _get_nested(load_raw_sevn_json(sevn_json), "voice.tts_voice_id") == "F3"

    assert "af_heart" in handler._handle_voice("af_heart", session_id="s")
    assert _get_nested(load_raw_sevn_json(sevn_json), "voice.tts_voice_id") == "af_heart"

    reject = handler._handle_voice("F9", session_id="s")
    assert "Unknown voice code" in reject
    assert _get_nested(load_raw_sevn_json(sevn_json), "voice.tts_voice_id") == "af_heart"


def test_voice_command_sets_session_override(tmp_path: Path) -> None:
    root = tmp_path / "w"
    root.mkdir()
    sevn_json = root / "sevn.json"
    sevn_json.write_text('{"schema_version":1,"workspace_root":"."}', encoding="utf-8")
    ws = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "test-token"},
        voice=VoiceConfig(tts_mode="off"),
    )
    layout = WorkspaceLayout.from_config(sevn_json, ws)
    conn = _conn()
    conn.execute(
        """
        INSERT INTO gateway_sessions(session_id, scope_key, channel, user_id, created_at, updated_at)
        VALUES (?,?,?,?,?,?)
        """,
        ("sess", "scope", "telegram", "1", "t", "t"),
    )
    conn.commit()
    sm = SessionManager(conn)
    handler = CoreCommandHandler(
        workspace=ws,
        layout=layout,
        router=AsyncMock(),
        sessions=sm,
    )
    assert "all" in handler._handle_voice("on", session_id="sess")
    assert sm.get_tts_mode_override("sess") == "all"
    assert ws.voice is not None
    assert ws.voice.tts_mode == "off"
    handler._handle_voice("reset", session_id="sess")
    assert sm.get_tts_mode_override("sess") is None
    conn.close()


@pytest.mark.asyncio
async def test_voice_disabled_skips_stt(tmp_path: Path, monkeypatch: Any) -> None:
    from sevn.gateway.util.strings import VOICE_DISABLED_USER_MESSAGE

    root = tmp_path / "w"
    root.mkdir()
    ws = WorkspaceConfig(
        schema_version=1,
        voice=VoiceConfig(enabled=False),
        gateway={"token": "x"},
    )
    conn = _conn()
    router: ChannelRouter | None = None
    scanned: list[str] = []
    try:
        sessions = SessionManager(conn)
        media = MediaStore(conn, root)
        scanner = LLMGuardScanner(root, ws)

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
            from sevn.security.llm_guard_scanner import ScanResult, ScanVerdict

            return ScanResult(
                verdict=ScanVerdict.allow,
                reasons=(),
                scores={},
                provider_used=None,
                details={},
            )

        monkeypatch.setattr(LLMGuardScanner, "scan_inbound", scan)
        router = ChannelRouter(
            workspace=ws,
            content_root=root,
            sessions=sessions,
            dispatcher=CommandDispatcher(),
            scanner=scanner,
            trace=NullTraceSink(),
            rate=TokenBucketLimiter(capacity=10.0, refill_per_second=10.0),
            media=media,
            run_turn=AsyncMock(),
        )

        class _Dl(TelegramAdapter):
            async def download_attachment(
                self, file_id: str, *, dest_dir: Path, **kwargs: Any
            ) -> Path:
                _ = file_id, kwargs
                dest_dir.mkdir(parents=True, exist_ok=True)
                p = dest_dir / "v.ogg"
                p.write_bytes(b"x")
                return p

        router.register_adapter(_Dl())
        await router.route_incoming(
            IncomingMessage(
                channel="telegram",
                user_id="1",
                text="[voice]",
                attachments=[{"type": "voice", "file_id": "f", "filename": "v.ogg"}],
                metadata={"chat_id": 1},
            ),
        )
        assert scanned == [VOICE_DISABLED_USER_MESSAGE]
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()
