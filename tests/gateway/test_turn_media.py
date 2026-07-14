"""W9 turn media plumbing + triager modality flags."""

from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from sevn.agent.triager.context import (
    ApprovedUserTurn,
    RegistrySnapshot,
    SessionView,
    TriagePromptContext,
)
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.agent.triager.prompt import build_triager_prompt_segments, concat_prompt_for_stub_llm
from sevn.agent.triager.run import _apply_attachment_modality_flags, triage_turn
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.turn.turn_media import (
    attachment_hints_for_triager,
    build_turn_media_summaries,
    hydrate_turn_media,
    infer_modality_flags,
    load_turn_media_summaries,
)
from sevn.security.llm_guard_scanner import LLMGuardScanner, ScanResult, ScanVerdict
from sevn.storage.migrate import apply_migrations
from tests.gateway.test_router import _memory_conn, _router_bundle


@pytest.mark.asyncio
async def test_image_attachment_surfaces_bytes_and_media_type(
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
        png_bytes = b"\x89PNG\r\n\x1a\n"
        b64 = base64.b64encode(png_bytes).decode("ascii")
        await router.route_incoming(
            IncomingMessage(
                channel="telegram",
                user_id="img",
                text="what is this?",
                attachments=[
                    {
                        "type": "photo",
                        "filename": "shot.png",
                        "data_base64": b64,
                    },
                ],
            ),
        )
        row = conn.execute(
            "SELECT session_id, turn_id FROM gateway_messages WHERE role='user' ORDER BY id DESC LIMIT 1",
        ).fetchone()
        assert row is not None
        sid, turn_id = str(row[0]), str(row[1])
        items = router.load_turn_media(sid, turn_id)
        assert len(items) == 1
        assert items[0].media_type == "image/png"
        assert items[0].data == png_bytes
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()


def test_pdf_attachment_hint_sets_requires_document_flag() -> None:
    hints = attachment_hints_for_triager(
        [
            {
                "kind": "document",
                "media_type": "application/pdf",
                "filename": "report.pdf",
                "rel_path": "report.pdf",
            },
        ],
    )
    vision, document = infer_modality_flags(hints)
    assert vision is False
    assert document is True
    base = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="Reading the PDF.",
        tools=["read"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.8,
        requires_vision=False,
        requires_document=False,
    )
    out = _apply_attachment_modality_flags(base, attachment_hints=hints)
    assert out.requires_document is True
    assert out.requires_vision is False


def test_image_attachment_hint_sets_requires_vision_flag() -> None:
    hints = [{"kind": "photo", "media_type": "image/jpeg", "name": "a.jpg"}]
    vision, document = infer_modality_flags(hints)
    assert vision is True
    assert document is False


@pytest.mark.asyncio
async def test_voice_attachment_excluded_from_turn_media_summaries(
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
        voice_bytes = b"OggS"
        b64 = base64.b64encode(voice_bytes).decode("ascii")
        stt = AsyncMock(return_value=("transcript: hello", {"transcript": "hello"}))
        monkeypatch.setattr(router, "_stt", type("S", (), {"transcribe_or_placeholder": stt})())
        await router.route_incoming(
            IncomingMessage(
                channel="telegram",
                user_id="voice",
                text="",
                attachments=[
                    {
                        "type": "voice",
                        "filename": "note.ogg",
                        "data_base64": b64,
                        "mime_type": "audio/ogg",
                    },
                ],
            ),
        )
        row = conn.execute(
            "SELECT session_id, turn_id, content, extras_json FROM gateway_messages "
            "WHERE role='user' ORDER BY id DESC LIMIT 1",
        ).fetchone()
        assert row is not None
        sid, turn_id, content, extras = str(row[0]), str(row[1]), str(row[2]), str(row[3])
        parsed = json.loads(extras)
        assert parsed.get("turn_media") in (None, [])
        assert "transcript" in content.lower() or "hello" in content.lower()
        assert router.load_turn_media(sid, turn_id) == ()
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_triager_prompt_includes_attachment_hints(monkeypatch: Any) -> None:
    workspace = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    ctx = TriagePromptContext(
        current_message="describe this",
        attachment_hints=[{"kind": "photo", "media_type": "image/png", "name": "x.png"}],
    )
    blob = concat_prompt_for_stub_llm(
        build_triager_prompt_segments(registry_snapshot=RegistrySnapshot(), triage_context=ctx),
    )
    assert "[attachments]" in blob
    assert "image/png" in blob

    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv(
        "SEVN_TRIAGER_STUB_JSON",
        json.dumps(
            {
                "intent": "NEW_REQUEST",
                "complexity": "B",
                "first_message": "Looking.",
                "tools": ["read"],
                "skills": [],
                "mcp_servers_required": [],
                "confidence": 0.9,
                "requires_vision": False,
                "requires_document": False,
                "disregard": False,
            },
        ),
    )
    result = await triage_turn(
        workspace=workspace,
        session=SessionView(session_id="s"),
        incoming=ApprovedUserTurn(
            text="describe this",
            attachment_descriptors=[
                {"kind": "photo", "media_type": "image/png", "name": "x.png"},
            ],
        ),
        registry_snapshot=RegistrySnapshot(),
        triage_context=ctx,
    )
    assert result.requires_vision is True
    assert result.requires_document is False


def test_load_turn_media_summaries_from_message_row() -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    conn.execute(
        """
        INSERT INTO gateway_sessions(session_id, scope_key, channel, user_id, created_at, updated_at)
        VALUES ('s1', 'telegram:u', 'telegram', 'u', 1, 1)
        """,
    )
    extras = json.dumps(
        {
            "turn_media": [
                {
                    "kind": "document",
                    "media_type": "application/pdf",
                    "filename": "a.pdf",
                    "rel_path": "a.pdf",
                },
            ],
        },
    )
    conn.execute(
        """
        INSERT INTO gateway_messages(
            session_id, role, kind, content, visible_to_llm, status, turn_id, extras_json, created_at
        ) VALUES ('s1', 'user', 'message', 'hi', 1, 'sent', 't1', ?, 1)
        """,
        (extras,),
    )
    conn.commit()
    loaded = load_turn_media_summaries(conn, "s1", "t1")
    assert loaded[0]["media_type"] == "application/pdf"


def test_hydrate_turn_media_reads_channel_files(tmp_path: Path) -> None:
    root = tmp_path / "w"
    media_dir = root / "channel_files" / "sess"
    media_dir.mkdir(parents=True)
    (media_dir / "pic.png").write_bytes(b"PNG")
    summaries = build_turn_media_summaries(
        [
            {
                "type": "photo",
                "filename": "pic.png",
                "data_base64": base64.b64encode(b"PNG").decode(),
            }
        ],
        media_dir=media_dir,
    )
    items = hydrate_turn_media("sess", summaries, root)
    assert items[0].data == b"PNG"
    assert items[0].media_type == "image/png"
