"""Wave 9 Telegram streaming edits + quick-action callbacks."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.executors.b_types import ResolvedTierBModel
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.tracing.sink import NullTraceSink
from sevn.channels.telegram import TelegramAdapter
from sevn.config.workspace_config import WorkspaceConfig, parse_workspace_config
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import (
    ChannelRouter,
    IncomingMessage,
    OutgoingMessage,
)
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.gateway.telegram.telegram_quick_actions import (
    GATEWAY_OUTBOUND_PHASE_KEY,
    build_quick_action_inline_keyboard,
    lookup_assistant_row_by_platform_message,
    parse_qa_callback_data,
)
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "triager"
_E2E_STUB = _FIXTURE_DIR / "e2e_tier_b_stub.json"


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


class _CaptureTelegram(TelegramAdapter):
    """Records outbound metadata and simulates progressive message ids."""

    def __init__(self) -> None:
        super().__init__(resolved_bot_token="test-token")
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self._next_mid = 100

    async def send(self, message: Any) -> list[str]:
        md = dict(message.metadata) if isinstance(message.metadata, dict) else {}
        self.sent.append((message.text, md))
        # When the router hints ``edit_message_id`` the real Telegram adapter calls
        # ``editMessageText`` and the returned message id is the *edited* id, not a
        # fresh one. Mirror that contract here so post-send markup attachment lands
        # on the right bubble.
        edit_hint = md.get("edit_message_id")
        if isinstance(edit_hint, int):
            return [str(edit_hint)]
        mid = self._next_mid
        self._next_mid += 1
        return [str(mid)]

    async def edit_reply_markup(self, **kwargs: Any) -> bool:
        self.sent.append(("__markup__", dict(kwargs)))
        return True


class _ScriptedTierB(ChatCompletionsTransport):
    def __init__(self, reply: str) -> None:
        super().__init__(proxy_base_url="http://telegram-streaming.test.invalid")
        self._reply = reply

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        _ = request
        return {
            "choices": [{"message": {"role": "assistant", "content": self._reply}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }


def _router_bundle(
    tmp_path: Path, conn: sqlite3.Connection, *, telegram: _CaptureTelegram
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
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=10.0, refill_per_second=5.0),
        media=MediaStore(conn, root),
        owner_user_ids=frozenset({"owner"}),
    )
    router.register_adapter(telegram)
    return router, ws, layout


@pytest.mark.asyncio
async def test_progressive_outbound_uses_edit_message_id(tmp_path: Path) -> None:
    """Early ack then final chunk edits the same Telegram message."""
    conn = _memory_conn()
    tg = _CaptureTelegram()
    router, _ws, _layout = _router_bundle(tmp_path, conn, telegram=tg)
    session_id = await router._sessions.ensure_session(
        scope_key="telegram:owner",
        channel="telegram",
        user_id="owner",
    )
    meta = {"chat_id": 42}
    await router.route_outgoing(
        OutgoingMessage(
            channel="telegram",
            user_id="owner",
            text="Thinking…",
            session_id=session_id,
            metadata={**meta, GATEWAY_OUTBOUND_PHASE_KEY: "early"},
        ),
    )
    await router.route_outgoing(
        OutgoingMessage(
            channel="telegram",
            user_id="owner",
            text="Done.",
            session_id=session_id,
            metadata={**meta, GATEWAY_OUTBOUND_PHASE_KEY: "final"},
        ),
    )
    assert len(tg.sent) == 2
    assert "edit_message_id" not in tg.sent[0][1]
    assert tg.sent[1][1].get("edit_message_id") == 100
    kb = tg.sent[1][1].get("inline_keyboard")
    assert isinstance(kb, dict)
    assert kb["inline_keyboard"][0][0]["callback_data"] == "qa:100:regen"
    conn.close()


@pytest.mark.asyncio
async def test_agent_turn_tier_b_streams_first_message_then_final(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Triager ``first_message`` persists; tier-B final is a separate Telegram bubble."""
    conn = _memory_conn()
    tg = _CaptureTelegram()
    router, _ws, _layout = _router_bundle(tmp_path, conn, telegram=tg)
    stub = json.loads(_E2E_STUB.read_text(encoding="utf-8"))
    stub["first_message"] = "One moment…"
    stub["complexity"] = "B"
    fixture_path = tmp_path / "stream_stub.json"
    fixture_path.write_text(json.dumps(stub), encoding="utf-8")
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(fixture_path))
    session_id = await router._sessions.ensure_session(
        scope_key="telegram:owner",
        channel="telegram",
        user_id="owner",
    )
    await router._sessions.add_message(
        session_id,
        role="user",
        kind="message",
        content="hello",
        visible_to_llm=1,
        status="sent",
        metadata_blob=json.dumps({"chat_id": 7}),
        turn_id="t-test",
    )
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-tier-b",
        transport=_ScriptedTierB("final answer"),
        budget=ModelBudget(model_id="openai/gpt-tier-b", regime=BudgetRegime.FREE_LOCAL),
    )

    async def factory(_ws: Any) -> ResolvedTierBModel:
        return bundle

    run_turn = build_agent_run_turn(
        router,
        conn,
        _ws,
        _layout,
        NullTraceSink(),
        tier_b_bundle_factory=factory,
    )
    router._run_turn = run_turn
    await run_turn(session_id, "corr-stream")
    texts = [t for t, _ in tg.sent if t != "__markup__"]
    assert texts[0] == "One moment…"
    # After Step 6 the final answer arrives as a router send carrying an
    # ``edit_message_id`` hint — the Telegram adapter converts that to
    # ``editMessageText`` against the placeholder. The placeholder ("…") and the
    # final answer ("final answer") are both in ``tg.sent`` but the final send's
    # metadata identifies the edit target so the user sees one bubble update,
    # not two fresh sends.
    assert "final answer" in texts
    assert "edit_message_id" not in tg.sent[0][1]
    final_meta = next(md for t, md in tg.sent if t == "final answer")
    assert final_meta.get("edit_message_id") == 101
    markup_calls = [md for t, md in tg.sent if t == "__markup__"]
    assert markup_calls
    assert markup_calls[-1].get("message_id") == 101
    conn.close()


@pytest.mark.asyncio
async def test_triager_persist_never_becomes_stream_anchor(tmp_path: Path) -> None:
    """``persist`` leaves the Triager bubble untouched; ``early``+``final`` edit executor only."""
    conn = _memory_conn()
    tg = _CaptureTelegram()
    router, _ws, _layout = _router_bundle(tmp_path, conn, telegram=tg)
    session_id = await router._sessions.ensure_session(
        scope_key="telegram:owner",
        channel="telegram",
        user_id="owner",
    )
    meta = {"chat_id": 42}
    await router.route_outgoing(
        OutgoingMessage(
            channel="telegram",
            user_id="owner",
            text="Hi! Let me tell you…",
            session_id=session_id,
            metadata={**meta, GATEWAY_OUTBOUND_PHASE_KEY: "persist"},
        ),
    )
    await router.route_outgoing(
        OutgoingMessage(
            channel="telegram",
            user_id="owner",
            text="Thinking…",
            session_id=session_id,
            metadata={**meta, GATEWAY_OUTBOUND_PHASE_KEY: "early"},
        ),
    )
    await router.route_outgoing(
        OutgoingMessage(
            channel="telegram",
            user_id="owner",
            text="Done.",
            session_id=session_id,
            metadata={**meta, GATEWAY_OUTBOUND_PHASE_KEY: "final"},
        ),
    )
    assert len(tg.sent) == 3
    assert tg.sent[0][0] == "Hi! Let me tell you…"
    assert "edit_message_id" not in tg.sent[0][1]
    assert tg.sent[2][1].get("edit_message_id") == 101
    assert tg.sent[0][1].get("edit_message_id") is None
    conn.close()


def test_build_quick_action_keyboard_and_parse() -> None:
    """Keyboard encodes Regen + thumbs; parser round-trips."""
    conn = _memory_conn()
    kb = build_quick_action_inline_keyboard(
        55,
        conn=conn,
        user_id="owner",
        gateway_message_id=1,
        platform_chat_id=9,
    )
    row = kb["inline_keyboard"][0]
    assert row[0]["callback_data"] == "qa:55:regen"
    assert parse_qa_callback_data(row[1]["callback_data"]) == (55, "up")
    assert parse_qa_callback_data(row[2]["callback_data"]) == (55, "down")
    assert len(row) == 3
    assert all("web_app" not in btn for btn in row)
    conn.close()


@pytest.mark.asyncio
async def test_qa_thumbs_callback_records_feedback(tmp_path: Path) -> None:
    """``qa:*:up`` bypass persists ``feedback_events`` for the assistant row."""
    conn = _memory_conn()
    router, ws, layout = _router_bundle(tmp_path, conn, telegram=_CaptureTelegram())
    build_agent_run_turn(router, conn, ws, layout, NullTraceSink())
    session_id = await router._sessions.ensure_session(
        scope_key="telegram:owner",
        channel="telegram",
        user_id="owner",
    )
    assistant_row = await router._sessions.add_message(
        session_id,
        role="assistant",
        kind="message",
        content="answer",
        visible_to_llm=1,
        status="sent",
        turn_id="t-test",
    )
    conn.execute(
        "UPDATE gateway_messages SET platform_message_id = ?, platform_chat_id = ? WHERE id = ?",
        ("200", "9", assistant_row),
    )
    conn.commit()
    handler = router._quick_action_callback_handler
    assert handler is not None
    msg = IncomingMessage(
        channel="telegram",
        user_id="owner",
        text="qa:200:up",
        metadata={"callback_data": "qa:200:up", "chat_id": 9},
    )
    assert CommandDispatcher().try_dispatch(msg)
    reply = await handler.handle(msg, session_id=session_id, is_owner=True)
    assert reply is not None
    row = conn.execute("SELECT kind FROM feedback_events").fetchone()
    assert row is not None
    assert row[0] == "thumbs_up"
    resolved = lookup_assistant_row_by_platform_message(
        conn, channel="telegram", platform_message_id=200, platform_chat_id="9"
    )
    assert resolved is not None
    assert resolved[0] == session_id
    conn.close()


@pytest.mark.asyncio
async def test_qa_regen_enqueues_run_turn(tmp_path: Path) -> None:
    """``qa:*:regen`` re-enqueues ``run_turn`` for the target session."""
    conn = _memory_conn()
    router, ws, layout = _router_bundle(tmp_path, conn, telegram=_CaptureTelegram())
    dispatched: list[str] = []

    async def _capture_run(sid: str, _cid: str) -> None:
        dispatched.append(sid)

    build_agent_run_turn(router, conn, ws, layout, NullTraceSink())
    router._run_turn = _capture_run
    session_id = await router._sessions.ensure_session(
        scope_key="telegram:owner",
        channel="telegram",
        user_id="owner",
    )
    await router._sessions.add_message(
        session_id,
        role="assistant",
        kind="message",
        content="answer",
        visible_to_llm=1,
        status="sent",
        turn_id="t-test",
    )
    conn.execute(
        "UPDATE gateway_messages SET platform_message_id = ? WHERE id = 1",
        ("300",),
    )
    conn.commit()
    handler = router._quick_action_callback_handler
    assert handler is not None
    msg = IncomingMessage(
        channel="telegram",
        user_id="owner",
        text="qa:300:regen",
        metadata={"callback_data": "qa:300:regen"},
    )
    await handler.handle(msg, session_id=session_id, is_owner=True)
    for _ in range(30):
        if dispatched:
            break
        await asyncio.sleep(0.05)
    assert dispatched == [session_id]
    conn.close()
