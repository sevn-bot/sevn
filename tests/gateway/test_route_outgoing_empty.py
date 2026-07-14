"""``route_outgoing`` empty-text behaviour (`specs/17-gateway.md` §2.4).

Wave 3 (CONVERSATION_REVIEW_2026-05-28.md §A3): empty / sanitizer-emptied
bodies now substitute :data:`TURN_EMPTY_FALLBACK_TEXT` so the user always sees
something. Attachment-only / TTS-only deliveries still bypass the fallback.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.channel_router import (
    TURN_EMPTY_FALLBACK_TEXT,
    ChannelAdapter,
    ChannelRouter,
    IncomingMessage,
    OutgoingMessage,
)
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations
from sevn.voice.tts import TextToSpeechPipeline


async def _noop_run_turn(_session_id: str, _correlation_id: str) -> None:
    return


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


class _StubAdapter(ChannelAdapter):
    """Records ``send`` invocations."""

    def __init__(self) -> None:
        self.sent: list[OutgoingMessage] = []

    @property
    def name(self) -> str:
        return "stub"

    def parse_webhook(self, payload: dict[str, Any]) -> IncomingMessage | None:
        _ = payload
        return None

    async def send(self, message: OutgoingMessage) -> list[str]:
        self.sent.append(message)
        return ["1"]


def _router(tmp_path: Path, conn: sqlite3.Connection, adapter: _StubAdapter) -> ChannelRouter:
    root = tmp_path / "w"
    root.mkdir()
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    sessions = SessionManager(conn)
    media = MediaStore(conn, root)
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=sessions,
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=media,
        run_turn=_noop_run_turn,
        tts_pipeline=TextToSpeechPipeline(
            (),
            voice_trigger_keywords=(),
            trace=NullTraceSink(),
            tts_output_dir=root / "tts",
        ),
    )
    router.register_adapter(adapter)
    return router


@pytest.mark.asyncio
async def test_route_outgoing_substitutes_fallback_for_empty_text(tmp_path: Path) -> None:
    """Wave 3 §A3: empty body sends the deterministic fallback string."""
    conn = _memory_conn()
    adapter = _StubAdapter()
    router = _router(tmp_path, conn, adapter)
    sid = await router._sessions.ensure_session(
        scope_key="stub:u1",
        channel="stub",
        user_id="u1",
    )
    await router.route_outgoing(
        OutgoingMessage(channel="stub", user_id="u1", text="   ", session_id=sid),
    )
    assert len(adapter.sent) == 1
    assert adapter.sent[0].text == TURN_EMPTY_FALLBACK_TEXT
    count = conn.execute(
        "SELECT COUNT(*) FROM gateway_messages WHERE session_id = ? AND role = 'assistant'",
        (sid,),
    ).fetchone()
    assert count is not None
    assert count[0] == 1


@pytest.mark.asyncio
async def test_route_outgoing_substitutes_fallback_when_sanitizer_empties(tmp_path: Path) -> None:
    """Wave 3 §A10: pure tool-call XML payloads collapse to the fallback string."""
    conn = _memory_conn()
    adapter = _StubAdapter()
    router = _router(tmp_path, conn, adapter)
    sid = await router._sessions.ensure_session(
        scope_key="stub:u1",
        channel="stub",
        user_id="u1",
    )
    await router.route_outgoing(
        OutgoingMessage(
            channel="stub",
            user_id="u1",
            text="<minimax:tool_call><invoke name='glob'></invoke></minimax:tool_call>",
            session_id=sid,
        ),
    )
    assert len(adapter.sent) == 1
    assert adapter.sent[0].text == TURN_EMPTY_FALLBACK_TEXT


@pytest.mark.asyncio
async def test_route_outgoing_delivers_attachment_with_empty_caption(tmp_path: Path) -> None:
    conn = _memory_conn()
    adapter = _StubAdapter()
    router = _router(tmp_path, conn, adapter)
    sid = await router._sessions.ensure_session(
        scope_key="stub:u1",
        channel="stub",
        user_id="u1",
    )
    await router.route_outgoing(
        OutgoingMessage(
            channel="stub",
            user_id="u1",
            text="",
            session_id=sid,
            metadata={"attachment_path": "/tmp/report.pdf", "attachment_kind": "document"},
        ),
    )
    assert len(adapter.sent) == 1
    assert adapter.sent[0].metadata.get("attachment_path") == "/tmp/report.pdf"
