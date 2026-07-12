"""MVP gateway agent glue (`plan/gateway-agent-glue-wave-plan.md` Wave 1)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.executors.b_types import ResolvedTierBModel
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.tracing.sink import NullTraceSink
from sevn.channels.telegram import TelegramAdapter
from sevn.config.workspace_config import (
    WorkspaceConfig,
    parse_workspace_config,
)
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media_store import MediaStore
from sevn.gateway.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "triager"
_E2E_STUB = _FIXTURE_DIR / "e2e_tier_b_stub.json"


def _openai_assistant_text(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class _ScriptedChatTransport(ChatCompletionsTransport):
    def __init__(self, fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> None:
        super().__init__(proxy_base_url="http://agent-turn-mvp.test.invalid")
        self._fn = fn

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        return await self._fn(dict(request))


class _CaptureTelegram(TelegramAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.sent_texts: list[str] = []

    async def send(self, message: Any) -> list[str]:
        self.sent_texts.append(message.text)
        return await super().send(message)


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _router_bundle(
    tmp_path: Path, conn: sqlite3.Connection
) -> tuple[ChannelRouter, WorkspaceConfig, WorkspaceLayout]:
    root = tmp_path / "w"
    root.mkdir()
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {"group_scope": "all", "relax_greeting_lists": False},
            "providers": {"tier_default": {"triager": "stub/model", "B": "stub/tier-b"}},
            "permissions": {"scope_narrowing": {"enabled": False}},
            "security": {"scanner": {"heuristic_only": True}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    layout = WorkspaceLayout(root / "sevn.json", root)
    sessions = SessionManager(conn)
    media = MediaStore(conn, root)
    from sevn.security.llm_guard_scanner import LLMGuardScanner

    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=sessions,
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=media,
    )
    return router, ws, layout


@pytest.mark.asyncio
async def test_agent_turn_mvp_triager_tier_b_outbound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stub Triager + scripted tier-B transport → ``route_outgoing`` / adapter send."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    async def _scripted(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text("Health check complete — all green.")

    async def _bundle_factory(_ws: WorkspaceConfig) -> ResolvedTierBModel:
        transport = _ScriptedChatTransport(_scripted)
        return ResolvedTierBModel(
            model_id="openai/gpt-mvp",
            transport=transport,
            budget=ModelBudget(model_id="openai/gpt-mvp", regime=BudgetRegime.FREE_LOCAL),
        )

    conn = _memory_conn()
    router, ws, layout = _router_bundle(tmp_path, conn)
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    run_turn = build_agent_run_turn(
        router,
        conn,
        ws,
        layout,
        NullTraceSink(),
        tier_b_bundle_factory=_bundle_factory,
    )
    router._run_turn = run_turn
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-mvp",
            channel="telegram",
            user_id="u-mvp",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="run the health check on my workspace",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 9001, "message_id": 1}),
            turn_id="t-test",
        )
        await run_turn(session_id, "corr-mvp-1")
        await router.session_manager.drain()
        assert cap.sent_texts
        joined = " ".join(cap.sent_texts)
        assert "On it" in joined or "quick check" in joined
        assert "Health check complete" in joined
    finally:
        conn.close()
