"""Outbound messaging tools (`plan/tools-skills-full-inventory-wave-plan.md` Wave 6)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.channel_router import (
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
from sevn.tools.base import ToolCall, ToolExecutor
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry
from sevn.voice.tts import TextToSpeechPipeline


async def _noop_run_turn(_session_id: str, _correlation_id: str) -> None:
    return


class _CaptureAdapter(ChannelAdapter):
    """Records outbound envelopes for assertions."""

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


class _FixedTTS:
    id = "fixed_tts"

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
        out_path.write_bytes(f"audio:{text}".encode())


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


@pytest.fixture
def executor() -> ToolExecutor:
    exe, _tool_set = build_session_registry(registry_version=1)
    return exe


def test_outbound_tools_registered(executor: ToolExecutor) -> None:
    names = {definition.name for definition in executor.definitions()}
    assert {"message", "send_file", "tts"} <= names
    send_file = next(d for d in executor.definitions() if d.name == "send_file")
    assert send_file.abortable is False


@pytest.mark.asyncio
async def test_message_tool_routes_via_channel_router(workspace: Path) -> None:
    captured: list[OutgoingMessage] = []

    class _Router:
        async def route_outgoing(self, msg: OutgoingMessage) -> None:
            captured.append(msg)

    ctx = ToolContext(
        session_id="sess-1",
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        channel_router=_Router(),
        outbound_user_id="user-42",
        outbound_metadata={"chat_id": 99},
        delivery_channel="stub",
    )
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="message", arguments={"text": "hello proactive"}),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    assert len(captured) == 1
    msg = captured[0]
    assert msg.text == "hello proactive"
    assert msg.channel == "stub"
    assert msg.user_id == "user-42"
    assert msg.session_id == "sess-1"
    assert msg.metadata["chat_id"] == 99


@pytest.mark.asyncio
async def test_send_file_tool_attaches_workspace_file(workspace: Path) -> None:
    captured: list[OutgoingMessage] = []
    sample = workspace / "report.txt"
    sample.write_text("payload", encoding="utf-8")

    class _Router:
        async def route_outgoing(self, msg: OutgoingMessage) -> None:
            captured.append(msg)

    ctx = ToolContext(
        session_id="sess-2",
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        channel_router=_Router(),
        outbound_user_id="user-7",
        delivery_channel="stub",
    )
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(
            name="send_file",
            arguments={"path": "report.txt", "caption": "here you go"},
        ),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["attachment_kind"] == "document"
    assert len(captured) == 1
    md = captured[0].metadata
    assert md["attachment_path"] == str(sample.resolve())
    assert md["attachment_filename"] == "report.txt"
    assert captured[0].text == "here you go"


@pytest.mark.asyncio
async def test_tts_tool_synthesizes_and_routes_audio(workspace: Path, tmp_path: Path) -> None:
    captured: list[OutgoingMessage] = []
    tts_dir = tmp_path / "tts"
    pipeline = TextToSpeechPipeline(
        [_FixedTTS()],
        voice_trigger_keywords=(),
        trace=NullTraceSink(),
        tts_output_dir=tts_dir,
    )

    class _Router:
        async def route_outgoing(self, msg: OutgoingMessage) -> None:
            captured.append(msg)

    ctx = ToolContext(
        session_id="sess-3",
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=1,
        trace=NullTraceSink(),
        permissions=AllowAllPermissionPolicy(),
        channel_router=_Router(),
        outbound_user_id="user-9",
        delivery_channel="stub",
        tts_pipeline=pipeline,
        turn_id="turn-tts",
    )
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="tts", arguments={"text": "spoken line"}),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["provider"] == "fixed_tts"
    assert len(captured) == 1
    assert captured[0].metadata["tts_audio_path"] == env["data"]["audio_path"]


@pytest.mark.asyncio
async def test_outbound_tools_capture_on_gateway_router(
    tmp_path: Path,
    workspace: Path,
) -> None:
    conn = _memory_conn()
    root = tmp_path / "gateway-ws"
    root.mkdir()
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    tts = TextToSpeechPipeline(
        [_FixedTTS()],
        voice_trigger_keywords=(),
        trace=NullTraceSink(),
        tts_output_dir=root / "tts",
    )
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        run_turn=_noop_run_turn,
        tts_pipeline=tts,
    )
    adapter = _CaptureAdapter()
    router.register_adapter(adapter)
    session_id = await router._sessions.ensure_session(
        scope_key="stub:user-1",
        channel="stub",
        user_id="user-1",
    )
    attachment = workspace / "note.txt"
    attachment.write_text("attached", encoding="utf-8")
    ctx = ToolContext(
        session_id=session_id,
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=1,
        trace=NullTraceSink(),
        permissions=AllowAllPermissionPolicy(),
        channel_adapter=adapter,
        channel_router=router,
        outbound_user_id="user-1",
        outbound_metadata={"chat_id": 123},
        delivery_channel="stub",
        tts_pipeline=tts,
        turn_id="turn-gateway",
    )
    exe, _ = build_session_registry(registry_version=1)
    message_raw = await exe.dispatch(
        ctx,
        ToolCall(name="message", arguments={"text": "via gateway"}),
    )
    assert json.loads(message_raw)["ok"] is True
    assert adapter.sent[-1].text == "via gateway"

    file_raw = await exe.dispatch(
        ctx,
        ToolCall(name="send_file", arguments={"path": "note.txt"}),
    )
    file_env = json.loads(file_raw)
    assert file_env["ok"] is True
    assert adapter.sent[-1].metadata["attachment_filename"] == "note.txt"

    tts_raw = await exe.dispatch(
        ctx,
        ToolCall(name="tts", arguments={"text": "voice note"}),
    )
    tts_env = json.loads(tts_raw)
    assert tts_env["ok"] is True
    assert adapter.sent[-1].metadata["tts_audio_path"] == tts_env["data"]["audio_path"]
