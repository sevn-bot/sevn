"""``send_file_tool`` surfaces Telegram adapter failures (`reactive-plum` Wave 1)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.channels.telegram import TelegramAdapter, TelegramConfig
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.channel_router import ChannelRouter
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media_store import MediaStore
from sevn.gateway.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations
from sevn.tools.base import ToolCall
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry
from sevn.voice.tts import TextToSpeechPipeline


async def _noop_run_turn(_session_id: str, _correlation_id: str) -> None:
    return


@pytest.mark.asyncio
async def test_send_file_tool_returns_failure_when_telegram_rejects(tmp_path: Path) -> None:
    """400 from ``sendDocument`` becomes a non-ok tool envelope."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    sample = workspace / "index.md"
    sample.write_text("# skills\n", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(
            200,
            json={
                "ok": False,
                "error_code": 400,
                "description": "Bad Request: file must be non-empty",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_migrations(conn)
        root = tmp_path / "w"
        root.mkdir()
        ws = WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        )
        sessions = SessionManager(conn)
        media = MediaStore(conn, root)
        tg = TelegramAdapter(config=TelegramConfig(bot_token="tok"), http_client=client)
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
        router.register_adapter(tg)
        sid = await sessions.ensure_session(
            scope_key="telegram:99",
            channel="telegram",
            user_id="99",
        )
        ctx = ToolContext(
            session_id=sid,
            workspace_path=workspace,
            workspace_id="wid",
            registry_version=1,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            channel_router=router,
            outbound_user_id="99",
            delivery_channel="telegram",
            outbound_metadata={"chat_id": 12345},
        )
        exe, _ = build_session_registry(registry_version=1)
        raw = await exe.dispatch(
            ctx,
            ToolCall(name="send_file", arguments={"path": "index.md"}),
        )
        env = json.loads(raw)
        assert env["ok"] is False
        assert "Bad Request" in env["error"]
