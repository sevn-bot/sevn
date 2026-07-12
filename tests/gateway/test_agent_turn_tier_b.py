"""Gateway tier-B registry glue (`plan/gateway-agent-glue-wave-plan.md` Wave 4)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sevn.agent.executors.b_types import (
    EXECUTOR_TIMEOUT_CANCEL_DETAIL,
    BTurnOutcome,
    ChannelPayload,
    ResolvedTierBModel,
)
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.tracing.sink import NullTraceSink
from sevn.channels.telegram import TelegramAdapter
from sevn.config.model_resolution import ModelSlot
from sevn.config.workspace_config import WorkspaceConfig, parse_workspace_config
from sevn.gateway import agent_turn as agent_turn_mod
from sevn.gateway.agent_turn import (
    _permission_policy_from_workspace,
    build_agent_run_turn,
)
from sevn.gateway.channel_router import ChannelRouter
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media_store import MediaStore
from sevn.gateway.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.plugins.runner import PluginHookChain
from sevn.storage.migrate import apply_migrations
from sevn.tools.permissions import AllowAllPermissionPolicy, DenyingPermissionPolicy
from sevn.tools.registry import build_session_registry
from sevn.tools.runtime_dispatch import RuntimeToolBindings
from sevn.workspace.layout import WorkspaceLayout

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "triager"
_E2E_STUB = _FIXTURE_DIR / "e2e_tier_b_stub.json"
_STREAM_GATEWAY_NO_INTRO = {
    "first_session_intro": {"enabled": False},
    "output": {"tier_b_answer_mode": "stream"},
    "token": "${SECRET:keychain:sevn.gateway.token}",
}
_TIER_B_MECHANICS_OVERRIDES = {
    "triager": {
        "group_scope": "all",
        "relax_greeting_lists": False,
        "fast_greeting_path": False,
    },
    "gateway": dict(_STREAM_GATEWAY_NO_INTRO),
}


def _openai_assistant_text(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class _ScriptedChatTransport(ChatCompletionsTransport):
    def __init__(self, fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> None:
        super().__init__(proxy_base_url="http://agent-turn-tier-b.test.invalid")
        self._fn = fn

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        return await self._fn(dict(request))


class _CaptureTelegram(TelegramAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.sent_texts: list[str] = []
        self.edited_texts: list[str] = []

    async def send(self, message: Any) -> list[str]:
        self.sent_texts.append(message.text)
        # Synthesize a channel-specific id so the finalizer can target an edit later.
        index = len(self.sent_texts)
        return [str(1000 + index)]

    async def edit_text(
        self,
        *,
        channel_message_id: str,
        new_text: str,
        metadata: dict[str, Any] | None = None,
        send_split_followups: bool = True,
    ) -> bool:
        _ = channel_message_id, metadata, send_split_followups
        self.edited_texts.append(new_text)
        return True


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _router_bundle(
    tmp_path: Path,
    conn: sqlite3.Connection,
    *,
    ws_overrides: dict[str, Any] | None = None,
    plugin_hooks: PluginHookChain | None = None,
) -> tuple[ChannelRouter, WorkspaceConfig, WorkspaceLayout]:
    root = tmp_path / "w"
    root.mkdir()
    payload: dict[str, Any] = {
        "schema_version": 1,
        "triager": {"group_scope": "all", "relax_greeting_lists": False},
        "providers": {"tier_default": {"triager": "stub/model", "B": "stub/tier-b"}},
        "permissions": {"scope_narrowing": {"enabled": False}},
        "security": {"scanner": {"heuristic_only": True}},
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    if ws_overrides:
        payload.update(ws_overrides)
    ws = parse_workspace_config(payload)
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
        plugin_hook_chain=plugin_hooks,
    )
    return router, ws, layout


def test_permission_policy_from_workspace_deny_all_profile() -> None:
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "permissions": {
                "default_profile": "locked",
                "profiles": {"locked": {"mode": "deny_all"}},
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    policy = _permission_policy_from_workspace(ws)
    assert isinstance(policy, DenyingPermissionPolicy)


def test_permission_policy_from_workspace_deny_tools_profile() -> None:
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "permissions": {
                "default_profile": "read_only",
                "profiles": {"read_only": {"deny_tools": ["integration_call"]}},
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    policy = _permission_policy_from_workspace(ws)
    assert policy.may_invoke("load_tool")
    assert not policy.may_invoke("integration_call")


@pytest.mark.asyncio
async def test_agent_turn_tier_b_builds_session_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``build_agent_run_turn`` calls ``build_session_registry`` with workspace + bindings."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    calls: list[dict[str, Any]] = []
    orig = build_session_registry

    def _spy(**kwargs: Any) -> tuple[Any, Any]:
        calls.append(dict(kwargs))
        return orig(**kwargs)

    monkeypatch.setattr(agent_turn_mod, "build_session_registry", _spy)

    async def _scripted(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text("Registry path ok.")

    async def _bundle_factory(_ws: WorkspaceConfig) -> ResolvedTierBModel:
        transport = _ScriptedChatTransport(_scripted)
        return ResolvedTierBModel(
            model_id="openai/gpt-tier-b",
            transport=transport,
            budget=ModelBudget(model_id="openai/gpt-tier-b", regime=BudgetRegime.FREE_LOCAL),
        )

    bindings = RuntimeToolBindings(integration=MagicMock())
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
        runtime_bindings=bindings,
    )
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-tier-b",
            channel="telegram",
            user_id="u-tier-b",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="run the health check on my workspace",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 9010, "message_id": 1}),
            turn_id="t-test",
        )
        await run_turn(session_id, "corr-tier-b-1")
        assert len(calls) == 1
        assert calls[0]["workspace_config"] is ws
        assert calls[0]["runtime_bindings"] is bindings
        assert calls[0]["workspace_root"] == layout.content_root
        assert calls[0]["layout"] is layout
        assert calls[0]["trace_sink"] is not None
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_agent_turn_tier_b_tool_context_and_model_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier-B dispatch wires ``ToolContext``, ``resolve_model_slot``, and channel adapter."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    slot_calls: list[ModelSlot] = []
    captured_ctx: dict[str, Any] = {}

    def _resolve_slot(ws: WorkspaceConfig, slot: ModelSlot) -> str:
        slot_calls.append(slot)
        return "openai/gpt-tier-b-test"

    def _fake_resolve_model(
        *,
        model_id: str,
        transport_name: str,
        proxy_base_url: str,
    ) -> tuple[Any, Any]:
        _ = transport_name, proxy_base_url

        async def _unused(_req: dict[str, Any]) -> dict[str, Any]:
            return _openai_assistant_text("unused")

        transport = _ScriptedChatTransport(_unused)
        return MagicMock(), transport

    monkeypatch.setattr(
        agent_turn_mod,
        "resolve_transport_for_model_id",
        lambda _providers, _model_id: "chat",
    )

    async def _fake_run_b_turn(**kwargs: Any) -> BTurnOutcome:
        captured_ctx["tool_context"] = kwargs["tool_context"]
        captured_ctx["transport_bundle"] = kwargs["transport_bundle"]
        return BTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text="done from harness."),),
            escalation=None,
            rounds_used=1,
        )

    monkeypatch.setattr(agent_turn_mod, "resolve_model_slot", _resolve_slot)
    monkeypatch.setattr(agent_turn_mod, "resolve_model", _fake_resolve_model)
    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _fake_run_b_turn)

    hooks = PluginHookChain(hooks=())
    conn = _memory_conn()
    router, ws, layout = _router_bundle(
        tmp_path,
        conn,
        ws_overrides={
            "permissions": {
                "default_profile": "read_only",
                "profiles": {"read_only": {"deny_tools": ["integration_call"]}},
                "scope_narrowing": {"enabled": False},
            },
        },
        plugin_hooks=hooks,
    )
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    run_turn = build_agent_run_turn(router, conn, ws, layout, NullTraceSink())
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-ctx",
            channel="telegram",
            user_id="u-ctx",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="run the health check on my workspace",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 9011, "message_id": 1}),
            turn_id="t-test",
        )
        await run_turn(session_id, "corr-ctx-1")
        ctx = captured_ctx["tool_context"]
        assert ctx.turn_id == "corr-ctx-1"
        assert ctx.channel_adapter is cap
        assert ctx.plugin_hooks is hooks
        assert ctx.delivery_channel == "telegram"
        assert not isinstance(ctx.permissions, AllowAllPermissionPolicy)
        assert not ctx.permissions.may_invoke("integration_call")
        assert ModelSlot.tier_b in slot_calls
        bundle = captured_ctx["transport_bundle"]
        assert bundle.model_id == "openai/gpt-tier-b-test"
        assert bundle.budget.model_id == "openai/gpt-tier-b-test"
        assert cap.sent_texts
        # Default ``tier_b_answer_mode`` is now ``stream`` (`PROBLEMS.md` Priority 2
        # Mode 1 / Step 6). The answer arrives as a router.route_outgoing send carrying
        # ``edit_message_id`` — the Telegram adapter converts that to ``editMessageText``
        # against the placeholder bubble. The placeholder "…" is the *first* tier-B send;
        # the final answer is the *last* tier-B send and carries the edit hint.
        assert "…" in cap.sent_texts
        assert any("done from harness" in t for t in cap.sent_texts)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_agent_turn_tier_b_stream_mode_pipes_progressive_text_to_placeholder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``stream`` mode → progressive accumulated text lands on the placeholder via edit.

    Reference: ``PROBLEMS.md`` Priority 2 Mode 1 / Step 6. The executor's
    ``streaming_sink`` callback forwards accumulated answer text into the
    ``TierBAnswerFinalizer.stream_update`` path, which calls
    ``adapter.edit_text`` (not router.route_outgoing — that's only on
    ``finalize(success)``).
    """
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    progressive_chunks = ["Once ", "Once upon ", "Once upon a time."]
    captured_sink_calls: list[str] = []

    async def _fake_run_b_turn(**kwargs: Any) -> BTurnOutcome:
        sink = kwargs.get("streaming_sink")
        if sink is not None:
            for chunk in progressive_chunks:
                await sink(chunk)
                captured_sink_calls.append(chunk)
        return BTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text="Once upon a time."),),
            escalation=None,
            rounds_used=1,
        )

    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _fake_run_b_turn)

    conn = _memory_conn()
    router, ws, layout = _router_bundle(
        tmp_path,
        conn,
        ws_overrides=dict(_TIER_B_MECHANICS_OVERRIDES),
    )
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    run_turn = build_agent_run_turn(router, conn, ws, layout, NullTraceSink())
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-stream",
            channel="telegram",
            user_id="u-stream",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="hello",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 9013, "message_id": 1}),
            turn_id="t-test",
        )
        await run_turn(session_id, "corr-stream-1")
        # Progressive edits landed on the placeholder via stream_update →
        # adapter.edit_text (the cheap path that doesn't route through the router).
        assert captured_sink_calls == progressive_chunks
        # ``stream_update`` strips whitespace before editing (no point shipping a
        # message that only differs by a trailing space).
        assert cap.edited_texts == [c.strip() for c in progressive_chunks]
        # Final answer landed as a router send carrying edit_message_id (Step 6
        # success path replaces the placeholder bubble via editMessageText).
        assert any("Once upon a time." in t for t in cap.sent_texts)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_agent_turn_tier_b_retry_with_full_index_after_initial_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Initial tier-B timeout → retry with full index → success edits same placeholder.

    Reference: ``PROBLEMS.md`` Priority 1(e) / Step 7c — exactly one retry with
    the full skills/INDEX exposed before escalating to tier C/D, all edits
    landing on the original placeholder.
    """
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    call_count = {"n": 0}
    full_index_seen: list[bool] = []

    async def _flaky_run_b_turn(**kwargs: Any) -> BTurnOutcome:
        call_count["n"] += 1
        full_index_seen.append(bool(kwargs.get("full_index")))
        if call_count["n"] == 1:
            # First attempt: simulate a timeout via raising TimeoutError directly.
            raise TimeoutError
        return BTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text="answer from full-index retry."),),
            escalation=None,
            rounds_used=1,
        )

    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _flaky_run_b_turn)

    conn = _memory_conn()
    router, ws, layout = _router_bundle(
        tmp_path,
        conn,
        ws_overrides=dict(_TIER_B_MECHANICS_OVERRIDES),
    )
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    run_turn = build_agent_run_turn(router, conn, ws, layout, NullTraceSink())
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-cascade",
            channel="telegram",
            user_id="u-cascade",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="hello",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 9020, "message_id": 1}),
            turn_id="t-test",
        )
        await run_turn(session_id, "corr-cascade-1")
        # Exactly two run_b_turn calls — initial (full_index=False) then retry
        # (full_index=True).
        assert call_count["n"] == 2
        assert full_index_seen == [False, True]
        # "Widening toolkit…" notice landed on the placeholder via stream_update
        # (adapter.edit_text), and the retry's final answer landed via the router
        # send with edit_message_id.
        assert any("Widening toolkit" in t for t in cap.edited_texts)
        assert any("answer from full-index retry." in t for t in cap.sent_texts)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_agent_turn_tier_b_timeout_with_fetch_triggers_summarize_not_full_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timeout with successful fetch → summarize retry; full-index widen skipped."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    call_count = {"n": 0}
    full_index_seen: list[bool] = []

    async def _timeout_then_summarize_run_b_turn(**kwargs: Any) -> BTurnOutcome:
        call_count["n"] += 1
        full_index_seen.append(bool(kwargs.get("full_index")))
        if call_count["n"] == 1:
            return BTurnOutcome(
                status="failed",
                final_messages=(),
                escalation=None,
                rounds_used=6,
                failure_detail=EXECUTOR_TIMEOUT_CANCEL_DETAIL,
                successful_tools_called=frozenset({"get_page_content", "serp"}),
            )
        return BTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text="Headlines summarized from spill."),),
            escalation=None,
            rounds_used=1,
        )

    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _timeout_then_summarize_run_b_turn)

    context_builds = {"n": 0}
    real_tool_context = agent_turn_mod._tool_context_for_turn

    def _counting_tool_context(**kwargs: Any) -> Any:
        context_builds["n"] += 1
        return real_tool_context(**kwargs)

    monkeypatch.setattr(agent_turn_mod, "_tool_context_for_turn", _counting_tool_context)

    conn = _memory_conn()
    router, ws, layout = _router_bundle(
        tmp_path,
        conn,
        ws_overrides=dict(_TIER_B_MECHANICS_OVERRIDES),
    )
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    run_turn = build_agent_run_turn(router, conn, ws, layout, NullTraceSink())
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-summarize",
            channel="telegram",
            user_id="u-summarize",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="hello",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 9022, "message_id": 1}),
            turn_id="t-test",
        )
        await run_turn(session_id, "corr-summarize-1")
        assert call_count["n"] == 2
        assert context_builds["n"] == 1
        assert full_index_seen == [False, False]
        assert not any("Widening toolkit" in t for t in cap.edited_texts)
        assert any("Headlines summarized from spill." in t for t in cap.sent_texts)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_agent_turn_tier_b_double_failure_escalates_to_cd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Initial timeout → retry timeout → escalate to tier C with same placeholder.

    Reference: ``PROBLEMS.md`` Priority 1(e) / Step 7d — when the full-index
    retry also fails, dispatch tier C/D rather than surfacing the generic "I
    couldn't answer." line.
    """
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    async def _always_timeout_run_b_turn(**_kwargs: Any) -> BTurnOutcome:
        raise TimeoutError

    cd_calls = {"n": 0}

    async def _fake_run_cd_dispatch(**kwargs: Any) -> None:
        cd_calls["n"] += 1
        finalizer = kwargs.get("finalizer")
        if finalizer is not None and not finalizer.is_finalized:
            await finalizer.finalize(
                status="success",
                text="tier-C took over and answered.",
            )

    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _always_timeout_run_b_turn)
    monkeypatch.setattr(agent_turn_mod, "_run_cd_dispatch", _fake_run_cd_dispatch)

    conn = _memory_conn()
    router, ws, layout = _router_bundle(
        tmp_path,
        conn,
        ws_overrides=dict(_TIER_B_MECHANICS_OVERRIDES),
    )
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    run_turn = build_agent_run_turn(router, conn, ws, layout, NullTraceSink())
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-double-fail",
            channel="telegram",
            user_id="u-double-fail",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="hello",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 9021, "message_id": 1}),
            turn_id="t-test",
        )
        await run_turn(session_id, "corr-cascade-2")
        # Tier C/D was dispatched exactly once after the double tier-B failure.
        assert cd_calls["n"] == 1
        # Placeholder showed the "Escalating to tier C…" handoff before tier C ran.
        assert any("Escalating to tier C" in t for t in cap.edited_texts)
        # Tier-C answer landed via the router (edit_message_id flow).
        assert any("tier-C took over" in t for t in cap.sent_texts)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_agent_turn_tier_b_two_message_finally_uses_placeholder_then_edit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``two_message_finally`` mode → 1 placeholder send + 1 finalize edit per tier-B turn.

    Reference: ``PROBLEMS.md`` Priority 2 contract item 5 ("exactly 2 send_message
    per tier-B turn"). With the finalizer engaged, the user-visible sequence is
    placeholder → edit, not two fresh sends.
    """
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    async def _fake_run_b_turn(**_kwargs: Any) -> BTurnOutcome:
        return BTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text="finalized answer."),),
            escalation=None,
            rounds_used=1,
        )

    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _fake_run_b_turn)

    conn = _memory_conn()
    router, ws, layout = _router_bundle(
        tmp_path,
        conn,
        ws_overrides={
            "gateway": {
                "output": {"tier_b_answer_mode": "two_message_finally"},
                "token": "${SECRET:keychain:sevn.gateway.token}",
            },
        },
    )
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    run_turn = build_agent_run_turn(router, conn, ws, layout, NullTraceSink())
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-finalizer",
            channel="telegram",
            user_id="u-finalizer",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="hello",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 9012, "message_id": 1}),
            turn_id="t-test",
        )
        await run_turn(session_id, "corr-finalizer-1")
        # Two-message-finally mode now (after Step 6) routes the success edit through
        # the router with an ``edit_message_id`` hint so the Telegram-level call is
        # ``editMessageText``. From the adapter test perspective: one placeholder
        # send ("…") plus one finalized-text send carrying the edit hint — that's
        # the "exactly 2 send_message calls per tier-B turn" invariant in its
        # router-mediated form (`PROBLEMS.md` Priority 2 contract item 5).
        assert cap.sent_texts.count("…") == 1
        assert cap.edited_texts == []  # success no longer uses adapter.edit_text
        assert any("finalized answer." in t for t in cap.sent_texts)
    finally:
        conn.close()


def test_cascade_budget_exceeds_tier_b_executor_timeout() -> None:
    """Import-time invariant: cascade budget must exceed a single tier-B executor pass."""
    from sevn.gateway import agent_turn

    assert agent_turn.CASCADE_BUDGET_S > agent_turn.TIER_B_EXECUTOR_TIMEOUT_S
