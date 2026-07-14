"""Multi-adapter gateway boot tests (Wave M1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.boot_registry import BootContext
from sevn.gateway.channel_boot import register_enabled_channel_adapters
from sevn.gateway.channel_router import ChannelRouter
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


@pytest.mark.asyncio
async def test_register_enabled_channel_adapters_telegram_and_webchat(tmp_path: Path) -> None:
    root = tmp_path / "w"
    root.mkdir()
    conn = _memory_conn()
    ws = WorkspaceConfig(
        schema_version=1,
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
        channels={
            "telegram": {"enabled": True},
            "webchat": {"enabled": True},
        },
    )
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=10.0, refill_per_second=5.0),
        media=MediaStore(conn, root),
    )
    layout = MagicMock()
    layout.sevn_json_path = root / "sevn.json"
    layout.content_root = root
    ctx = BootContext(
        app=MagicMock(),
        workspace=ws,
        layout=layout,
        conn=conn,
        trace=NullTraceSink(),
        gateway_router=router,
        process_settings=None,
        content_root=root,
    )
    await register_enabled_channel_adapters(ctx)
    names = set(router.adapter_names())
    assert "webchat" in names
    assert router.platform_runtime.get("webchat") is not None


@pytest.mark.asyncio
async def test_register_skips_disabled_channel(tmp_path: Path) -> None:
    root = tmp_path / "w"
    root.mkdir()
    conn = _memory_conn()
    ws = WorkspaceConfig(
        schema_version=1,
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
        channels={
            "telegram": {"enabled": False},
            "webchat": {"enabled": True},
        },
    )
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=10.0, refill_per_second=5.0),
        media=MediaStore(conn, root),
    )
    layout = MagicMock()
    layout.sevn_json_path = root / "sevn.json"
    layout.content_root = root
    ctx = BootContext(
        app=MagicMock(),
        workspace=ws,
        layout=layout,
        conn=conn,
        trace=NullTraceSink(),
        gateway_router=router,
        process_settings=None,
        content_root=root,
    )
    await register_enabled_channel_adapters(ctx)
    assert "telegram" not in router.adapter_names()
    assert "webchat" in router.adapter_names()
