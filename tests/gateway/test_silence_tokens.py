"""Silence token outbound filters (Wave M1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.channel_router import ChannelRouter, OutgoingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media_store import MediaStore
from sevn.gateway.rate_limit import TokenBucketLimiter
from sevn.gateway.response_filters import is_intentional_silence_response
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations


class _SilentAdapter:
    name = "webchat"

    async def start(self, _router: Any) -> None:
        return None

    async def stop(self) -> None:
        return None

    def parse_webhook(self, _body: dict[str, Any]) -> None:
        return None

    send = AsyncMock(return_value=[])


def test_is_intentional_silence_response_markers() -> None:
    assert is_intentional_silence_response("[SILENT]")
    assert is_intentional_silence_response("NO_REPLY")
    assert not is_intentional_silence_response("Please NO_REPLY later")
    assert not is_intentional_silence_response("")


@pytest.mark.asyncio
async def test_route_outgoing_suppresses_silence_token(tmp_path: Path) -> None:
    root = tmp_path / "w"
    root.mkdir()
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    ws = WorkspaceConfig(
        schema_version=1,
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    sessions = SessionManager(conn)
    adapter = _SilentAdapter()
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=sessions,
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=AsyncMock(),
        rate=TokenBucketLimiter(capacity=10.0, refill_per_second=5.0),
        media=MediaStore(conn, root),
    )
    router.register_adapter(adapter)  # type: ignore[arg-type]
    session_id = await sessions.ensure_session(
        scope_key="webchat:u1",
        channel="webchat",
        user_id="u1",
    )
    await router.route_outgoing(
        OutgoingMessage(
            channel="webchat",
            user_id="u1",
            text="[SILENT]",
            session_id=session_id,
        ),
    )
    adapter.send.assert_not_called()
    row = conn.execute(
        "SELECT content FROM gateway_messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == ""
