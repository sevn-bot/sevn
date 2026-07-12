"""Gateway ``/steer`` enqueue + executor injection (`plan/gateway-agent-glue-wave-plan.md` Wave 7)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sevn.agent.executors.b_types import BTurnOutcome, ChannelPayload, ResolvedTierBModel
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.tracing.sink import NullTraceSink
from sevn.channels.telegram import TelegramAdapter
from sevn.config.workspace_config import (
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
    parse_workspace_config,
)
from sevn.gateway import agent_turn as agent_turn_mod
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media_store import MediaStore
from sevn.gateway.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.gateway.steer_store import SessionSteerStore
from sevn.gateway.strings import (
    STEER_ACK_V1,
    STEER_BUFFER_FULL_V1,
    STEER_NOT_AVAILABLE_V1,
    STEER_NOT_OWNER_V1,
    STEER_USAGE_V1,
)
from sevn.security.llm_guard_scanner import LLMGuardScanner, ScanResult, ScanVerdict
from sevn.storage.migrate import apply_migrations
from sevn.tools.runtime_dispatch import RuntimeToolBindings
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
        super().__init__(proxy_base_url="http://steer-inject.test.invalid")
        self._fn = fn
        self.requests: list[dict[str, Any]] = []

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        req = dict(request)
        self.requests.append(req)
        return await self._fn(req)


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


def _router(
    tmp_path: Path,
    conn: sqlite3.Connection,
    *,
    steer_store: SessionSteerStore | None = None,
    owner_ids: frozenset[str] | None = None,
) -> ChannelRouter:
    root = tmp_path / "w"
    root.mkdir()
    ws = WorkspaceConfig(
        schema_version=1,
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    store = steer_store or SessionSteerStore(max_pending=4)
    return ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(steer_store=store),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        owner_user_ids=owner_ids or frozenset({"owner"}),
        steer_store=store,
    )


@pytest.fixture
def allow_scan(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_session_steer_store_enqueue_and_pop_order() -> None:
    store = SessionSteerStore(max_pending=2)
    assert store.enqueue("s1", "first").accepted is True
    assert store.enqueue("s1", "second").accepted is True
    assert store.enqueue("s1", "third").buffer_full is True
    inject = store.steer_inject_for("s1")
    assert inject.pop_pending() == "first"
    assert inject.pop_pending() == "second"
    assert inject.pop_pending() is None


def test_dispatcher_steer_without_store_returns_legacy_copy() -> None:
    dispatcher = CommandDispatcher()
    reply = dispatcher.bypass_reply_text(
        IncomingMessage(channel="telegram", user_id="owner", text="/steer fix it"),
        session_id="s1",
        is_owner=True,
    )
    assert reply == STEER_NOT_AVAILABLE_V1


def test_dispatcher_steer_owner_enqueue_ack() -> None:
    store = SessionSteerStore(max_pending=2)
    dispatcher = CommandDispatcher(steer_store=store)
    reply = dispatcher.bypass_reply_text(
        IncomingMessage(channel="telegram", user_id="owner", text="/steer fix it"),
        session_id="s1",
        is_owner=True,
    )
    assert reply == STEER_ACK_V1
    assert store.pending_count("s1") == 1


def test_dispatcher_steer_rejects_non_owner() -> None:
    store = SessionSteerStore()
    dispatcher = CommandDispatcher(steer_store=store)
    reply = dispatcher.bypass_reply_text(
        IncomingMessage(channel="telegram", user_id="guest", text="/steer fix it"),
        session_id="s1",
        is_owner=False,
    )
    assert reply == STEER_NOT_OWNER_V1
    assert store.pending_count("s1") == 0


def test_dispatcher_steer_empty_usage() -> None:
    dispatcher = CommandDispatcher(steer_store=SessionSteerStore())
    reply = dispatcher.bypass_reply_text(
        IncomingMessage(channel="telegram", user_id="owner", text="/steer"),
        session_id="s1",
        is_owner=True,
    )
    assert reply == STEER_USAGE_V1


def test_dispatcher_steer_buffer_full() -> None:
    store = SessionSteerStore(max_pending=1)
    dispatcher = CommandDispatcher(steer_store=store)
    assert (
        dispatcher.bypass_reply_text(
            IncomingMessage(channel="telegram", user_id="owner", text="/steer one"),
            session_id="s1",
            is_owner=True,
        )
        == STEER_ACK_V1
    )
    assert (
        dispatcher.bypass_reply_text(
            IncomingMessage(channel="telegram", user_id="owner", text="/steer two"),
            session_id="s1",
            is_owner=True,
        )
        == STEER_BUFFER_FULL_V1
    )


@pytest.mark.asyncio
async def test_steer_bypass_route_incoming_enqueues(
    tmp_path: Path,
    allow_scan: None,
) -> None:
    conn = _memory_conn()
    store = SessionSteerStore(max_pending=4)
    router = _router(tmp_path, conn, steer_store=store)
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    try:
        await router.route_incoming(
            IncomingMessage(channel="telegram", user_id="owner", text="/steer skip step"),
        )
        assert cap.sent_texts == [STEER_ACK_V1]
        row = conn.execute("SELECT session_id FROM gateway_sessions").fetchone()
        assert row is not None
        assert store.pending_count(str(row[0])) == 1
    finally:
        await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_agent_turn_passes_steer_buffer_to_tier_b(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-enqueued steer text reaches ``run_b_turn`` via glue ``steer_buffer``."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    captured: dict[str, Any] = {}

    async def _fake_run_b_turn(**kwargs: Any) -> BTurnOutcome:
        captured["steer_buffer"] = kwargs.get("steer_buffer")
        steer = kwargs.get("steer_buffer")
        assert steer is not None
        assert steer.pop_pending() == "priority: tests"
        return BTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text="done"),),
            escalation=None,
            rounds_used=1,
        )

    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _fake_run_b_turn)

    conn = _memory_conn()
    store = SessionSteerStore(max_pending=4)
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
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(steer_store=store),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        steer_store=store,
    )
    cap = _CaptureTelegram()
    router.register_adapter(cap)

    async def _bundle(_ws: WorkspaceConfig) -> ResolvedTierBModel:
        async def _one(_req: dict[str, Any]) -> dict[str, Any]:
            return _openai_assistant_text("unused")

        return ResolvedTierBModel(
            model_id="openai/gpt-tier-b",
            transport=_ScriptedChatTransport(_one),
            budget=ModelBudget(model_id="openai/gpt-tier-b", regime=BudgetRegime.FREE_LOCAL),
        )

    run_turn = build_agent_run_turn(
        router,
        conn,
        ws,
        layout,
        NullTraceSink(),
        tier_b_bundle_factory=_bundle,
        runtime_bindings=RuntimeToolBindings(integration=MagicMock()),
    )
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-steer",
            channel="telegram",
            user_id="u-steer",
        )
        store.enqueue(session_id, "priority: tests")
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="run health check",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 42}),
            turn_id="t-test",
        )
        await run_turn(session_id, "corr-steer-1")
        assert "steer_buffer" in captured
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_agent_turn_steer_injected_at_tier_b_provider_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queued steer appears in tier-B provider messages at the LLM boundary."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    transport_holder: dict[str, _ScriptedChatTransport] = {}

    async def _scripted(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text("ack")

    async def _bundle(_ws: WorkspaceConfig) -> ResolvedTierBModel:
        transport = _ScriptedChatTransport(_scripted)
        transport_holder["transport"] = transport
        return ResolvedTierBModel(
            model_id="openai/gpt-tier-b",
            transport=transport,
            budget=ModelBudget(model_id="openai/gpt-tier-b", regime=BudgetRegime.FREE_LOCAL),
        )

    monkeypatch.setattr(agent_turn_mod, "resolve_model_slot", lambda _ws, slot: "openai/gpt-tier-b")
    monkeypatch.setattr(
        agent_turn_mod,
        "resolve_transport_for_model_id",
        lambda _providers, _model_id: "chat",
    )

    conn = _memory_conn()
    store = SessionSteerStore(max_pending=4)
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
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(steer_store=store),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        steer_store=store,
    )
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    run_turn = build_agent_run_turn(
        router,
        conn,
        ws,
        layout,
        NullTraceSink(),
        tier_b_bundle_factory=_bundle,
        runtime_bindings=RuntimeToolBindings(integration=MagicMock()),
    )
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-steer-live",
            channel="telegram",
            user_id="u-steer-live",
        )
        store.enqueue(session_id, "priority: live inject")
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="run health check",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 43}),
            turn_id="t-test",
        )
        await run_turn(session_id, "corr-steer-live")
        transport = transport_holder["transport"]
        assert transport.requests
        dumped = json.dumps(transport.requests[0].get("messages"))
        assert "[Owner steer] priority: live inject" in dumped
    finally:
        conn.close()
