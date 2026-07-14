"""Gateway tests — bound Telegram topics bypass Triager for coding agents."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.workspace_config import (
    WorkspaceConfig,
)
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations


class _CaptureTelegram:
    channel = "telegram"
    name = "telegram"

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, msg: object) -> None:
        text = getattr(msg, "text", "")
        self.sent.append(str(text))


def _workspace_with_bindings() -> WorkspaceConfig:
    return WorkspaceConfig.model_validate(
        {
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            "security": {"scanner": {"heuristic_only": True}},
            "providers": {
                "use_main_model_for_all": False,
                "tier_default": {"triager": "stub/triager", "B": "stub/tier-b"},
            },
            "coding_agents": {
                "enabled": True,
                "agents": {
                    "bound-agent": {
                        "type": "alrca",
                        "enabled": True,
                        "executor": "cursor",
                        "telegram_bindings": [
                            {"chat_id": "-100777", "topic_ids": [42]},
                        ],
                    },
                },
            },
        },
    )


def _build_router(tmp_path: Path) -> tuple[ChannelRouter, _CaptureTelegram, AsyncMock]:
    root = tmp_path / "w"
    root.mkdir()
    ws = _workspace_with_bindings()
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    cap = _CaptureTelegram()
    run_turn = AsyncMock()
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        run_turn=run_turn,
    )
    router.register_adapter(cap)
    return router, cap, run_turn


@pytest.mark.asyncio
async def test_bound_topic_routes_to_coding_agent_without_run_turn(tmp_path: Path) -> None:
    router, cap, run_turn = _build_router(tmp_path)
    msg = IncomingMessage(
        channel="telegram",
        user_id="99",
        text="hello from bound topic",
        metadata={"chat_id": -100777, "topic_id": 42},
    )
    await router.route_incoming(msg)
    await asyncio.sleep(0.05)
    run_turn.assert_not_called()
    assert cap.sent
    assert "bound-agent" in cap.sent[0] or "ALRCA agent" in cap.sent[0]


@pytest.mark.asyncio
async def test_unbound_topic_still_enqueues_triager(tmp_path: Path) -> None:
    router, cap, run_turn = _build_router(tmp_path)
    msg = IncomingMessage(
        channel="telegram",
        user_id="99",
        text="normal sevn message",
        metadata={"chat_id": -100777, "topic_id": 99},
    )
    await router.route_incoming(msg)
    await asyncio.sleep(0.05)
    run_turn.assert_called()
    assert not cap.sent
