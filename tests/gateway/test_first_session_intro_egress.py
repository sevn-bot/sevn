"""First-session tier-B egress profile (`specs/17-gateway.md` §3.2)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.executors import b_harness as b_harness_mod
from sevn.agent.executors.b_types import BTurnOutcome, ChannelPayload, ResolvedTierBModel
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.tracing.sink import NullTraceSink
from sevn.channels.telegram import TelegramAdapter
from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway import agent_turn as agent_turn_mod
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner, ScanResult, ScanVerdict
from sevn.skills.manager import SkillsManager
from sevn.storage.migrate import apply_migrations
from sevn.tools.registry import ToolSet, TracingToolExecutor
from sevn.voice.tts import TextToSpeechPipeline
from sevn.workspace.layout import WorkspaceLayout

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "triager"
_E2E_STUB = _FIXTURE_DIR / "e2e_tier_b_stub.json"


class _CaptureTelegram(TelegramAdapter):
    def __init__(self) -> None:
        super().__init__(resolved_bot_token="test-token")
        self.sent_texts: list[str] = []

    async def send(self, message: Any) -> list[str]:
        self.sent_texts.append(message.text)
        return ["1"]

    async def send_chat_action(
        self,
        *,
        chat_id: int,
        action: str,
        message_thread_id: int | None = None,
    ) -> None:
        _ = chat_id, action, message_thread_id


def _instant_build_session_registry(**kwargs: Any) -> tuple[Any, Any]:
    _ = kwargs
    exe = TracingToolExecutor()
    tool_set = ToolSet(registry_version=1, native=(), mcp=(), skill_descriptions={})
    return exe, tool_set


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _router_bundle(
    tmp_path: Path, conn: sqlite3.Connection
) -> tuple[ChannelRouter, Any, WorkspaceLayout]:
    root = tmp_path / "w"
    root.mkdir()
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "providers": {"tier_default": {"triager": "stub/model", "B": "stub/tier-b"}},
            "permissions": {"scope_narrowing": {"enabled": False}},
            "security": {"scanner": {"heuristic_only": True}},
            "lcm": {"enabled": False},
            "gateway": {
                "output": {"tier_b_answer_mode": "stream"},
                "token": "${SECRET:keychain:sevn.gateway.token}",
            },
        },
    )
    layout = WorkspaceLayout(root / "sevn.json", root)
    sessions = SessionManager(conn)
    media = MediaStore(conn, root)
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=sessions,
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=media,
        run_turn=lambda _s, _c: asyncio.sleep(0),
        tts_pipeline=TextToSpeechPipeline(
            (),
            voice_trigger_keywords=(),
            trace=NullTraceSink(),
            tts_output_dir=root / "tts",
        ),
    )
    return router, ws, layout


@pytest.mark.asyncio
async def test_intro_turn_uses_4096_max_tokens_and_no_streaming_sink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First-session intro disables stream and passes intro max_output_tokens."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))
    SkillsManager.reset_singletons_for_tests()
    conn = _memory_conn()
    router, ws, layout = _router_bundle(tmp_path, conn)
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    captured: dict[str, Any] = {}
    b_turn_done = asyncio.Event()

    async def _fake_run_b_turn(**kwargs: Any) -> BTurnOutcome:
        captured.update(kwargs)
        b_turn_done.set()
        return BTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text="Intro done."),),
            escalation=None,
            rounds_used=1,
        )

    async def _bundle(_workspace: Any) -> ResolvedTierBModel:
        from sevn.agent.providers.transport import ChatCompletionsTransport

        class _Noop(ChatCompletionsTransport):
            async def complete(self, request: dict[str, object]) -> dict[str, object]:
                _ = request
                return {
                    "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }

        return ResolvedTierBModel(
            model_id="stub/tier-b",
            transport=_Noop(proxy_base_url="http://noop.test"),
            budget=ModelBudget(model_id="stub/tier-b", regime=BudgetRegime.FREE_LOCAL),
        )

    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _fake_run_b_turn)
    monkeypatch.setattr(b_harness_mod, "run_b_turn", _fake_run_b_turn)
    monkeypatch.setattr(agent_turn_mod, "build_session_registry", _instant_build_session_registry)
    run_turn = build_agent_run_turn(
        router,
        conn,
        ws,
        layout,
        NullTraceSink(),
        tier_b_bundle_factory=_bundle,
    )
    router._run_turn = run_turn

    async def _allow_scan(
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

    monkeypatch.setattr(LLMGuardScanner, "scan_inbound", _allow_scan)

    try:
        await router.route_incoming(
            IncomingMessage(
                channel="telegram", user_id="u-intro", text="hi", metadata={"chat_id": 1}
            ),
        )
        await asyncio.wait_for(b_turn_done.wait(), timeout=5.0)
        assert captured.get("max_output_tokens") == 4096
        assert captured.get("first_session_intro") is True
        assert captured.get("streaming_sink") is None
        assert "FIRST_SESSION_INTRO" in (captured.get("extra_instructions") or "")
    finally:
        await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_intro_executor_exception_skips_full_index_retry_and_notifies_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Intro failure must not call full-index retry; user sees intro failure text."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    full_index_calls: list[str] = []

    async def _fake_run_b_turn(**kwargs: Any) -> BTurnOutcome:
        _ = kwargs
        raise RuntimeError("upstream invalid params")

    async def _fake_full_index_retry(**kwargs: Any) -> tuple[BTurnOutcome | None, str | None]:
        full_index_calls.append(kwargs.get("first_attempt_reason") or "unknown")
        return None, "exception"

    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _fake_run_b_turn)
    monkeypatch.setattr(agent_turn_mod, "_run_full_index_retry", _fake_full_index_retry)
    monkeypatch.setattr(agent_turn_mod, "build_session_registry", _instant_build_session_registry)

    conn = _memory_conn()
    router, ws, layout = _router_bundle(tmp_path, conn)
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    run_turn = build_agent_run_turn(router, conn, ws, layout, NullTraceSink())

    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-intro-fail",
            channel="telegram",
            user_id="u-intro-fail",
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
        await run_turn(session_id, "corr-intro-fail")
        assert full_index_calls == []
        assert any(
            "couldn't finish the first-session introduction" in t.lower() for t in cap.sent_texts
        )
    finally:
        conn.close()
