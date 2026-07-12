"""Wave 3 outbound UX: typing, early ``first_message``, voice metadata."""

from __future__ import annotations

import asyncio
import base64
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
from sevn.gateway.channel_router import (
    ChannelAdapter,
    ChannelRouter,
    IncomingMessage,
    OutgoingMessage,
)
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media_store import MediaStore
from sevn.gateway.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner, ScanResult, ScanVerdict
from sevn.storage.migrate import apply_migrations
from sevn.voice.backends import TranscriptionResult
from sevn.voice.stt import SpeechToTextPipeline
from sevn.voice.tts import TextToSpeechPipeline
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
        super().__init__(proxy_base_url="http://outbound-early-ack.test.invalid")
        self._fn = fn

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        return await self._fn(dict(request))


class _CaptureTelegram(TelegramAdapter):
    def __init__(self) -> None:
        super().__init__(resolved_bot_token="test-token")
        self.sent_texts: list[str] = []
        self.chat_actions: list[dict[str, Any]] = []
        self.outbound_meta: list[dict[str, Any]] = []

    async def send(self, message: Any) -> list[str]:
        self.sent_texts.append(message.text)
        self.outbound_meta.append(dict(message.metadata))
        return ["1"]

    async def send_chat_action(
        self,
        *,
        chat_id: int,
        action: str = "typing",
        message_thread_id: int | None = None,
    ) -> None:
        self.chat_actions.append(
            {
                "chat_id": chat_id,
                "action": action,
                "message_thread_id": message_thread_id,
            }
        )


class _SlowTierBTransport(ChatCompletionsTransport):
    """Records when tier-B LLM starts relative to outbound sends."""

    def __init__(self, gate: asyncio.Event, order: list[str]) -> None:
        super().__init__(proxy_base_url="http://slow-tier-b.test.invalid")
        self._gate = gate
        self._order = order

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        self._order.append("tier_b_start")
        await self._gate.wait()
        return _openai_assistant_text("Executor finished.")


class _FixedSTT:
    id = "fixed_stt"

    async def is_available(self) -> bool:
        return True

    async def transcribe(
        self,
        *,
        audio_path: Path,
        mime_type: str | None,
        duration_s: float | None,
        locale: str | None = None,
    ) -> TranscriptionResult:
        _ = mime_type, duration_s, locale
        assert audio_path.is_file()
        return TranscriptionResult(text="voice user said hi", provider=self.id, confidence=0.95)


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


async def _noop_run_turn(_session_id: str, _correlation_id: str) -> None:
    return


def _router_bundle(
    tmp_path: Path,
    conn: sqlite3.Connection,
    *,
    run_turn: Any = _noop_run_turn,
    stt: SpeechToTextPipeline | None = None,
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
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=sessions,
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=media,
        run_turn=run_turn,
        stt_pipeline=stt,
        tts_pipeline=TextToSpeechPipeline(
            (),
            voice_trigger_keywords=(),
            trace=NullTraceSink(),
            tts_output_dir=root / "tts",
        ),
    )
    return router, ws, layout


@pytest.mark.asyncio
async def test_telegram_typing_after_scanner_allow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``sendChatAction(typing)`` fires post-scanner without blocking inbound."""
    conn = _memory_conn()
    router, _, _ = _router_bundle(tmp_path, conn)
    cap = _CaptureTelegram()
    router.register_adapter(cap)

    async def _allow_stub(
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

    monkeypatch.setattr(LLMGuardScanner, "scan_inbound", _allow_stub)

    msg = IncomingMessage(
        channel="telegram",
        user_id="42",
        text="hello",
        metadata={"chat_id": 9001, "topic_id": 7},
    )
    await router.route_incoming(msg)
    await asyncio.sleep(0.05)
    assert cap.chat_actions == [
        {"chat_id": 9001, "action": "typing", "message_thread_id": 7},
    ]
    conn.close()


@pytest.mark.asyncio
async def test_first_message_before_tier_b_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Triager opening line is routed before tier-B ``run_b_turn`` completes."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    gate = asyncio.Event()
    order: list[str] = []

    class _CaptureWithOrder(_CaptureTelegram):
        async def send(self, message: Any) -> list[str]:
            order.append(message.text)
            return await super().send(message)

    async def _bundle_factory(_ws: WorkspaceConfig) -> ResolvedTierBModel:
        return ResolvedTierBModel(
            model_id="openai/gpt-slow",
            transport=_SlowTierBTransport(gate, order),
            budget=ModelBudget(model_id="openai/gpt-slow", regime=BudgetRegime.FREE_LOCAL),
        )

    conn = _memory_conn()
    router, ws, layout = _router_bundle(tmp_path, conn)
    cap = _CaptureWithOrder()
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
            scope_key="telegram:u-early",
            channel="telegram",
            user_id="u-early",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="run health check",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 1}),
            turn_id="t-test",
        )
        dispatch_task = asyncio.create_task(run_turn(session_id, "corr-early-1"))
        for _ in range(40):
            if cap.sent_texts:
                break
            await asyncio.sleep(0.05)
        assert cap.sent_texts
        assert cap.sent_texts[0] == "On it — running a quick check."
        gate.set()
        await dispatch_task
        await router.session_manager.drain()
        assert "Executor finished." in cap.sent_texts[-1]
        assert "tier_b_start" in order
        assert order.index("On it — running a quick check.") < order.index("tier_b_start")
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_voice_user_text_last_turn_persisted_on_inbound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """STT transcript is stored on the user row for downstream outbound metadata."""
    conn = _memory_conn()
    stt = SpeechToTextPipeline(
        [_FixedSTT()],
        stt_confidence_reprompt_threshold=0.7,
        trace=NullTraceSink(),
    )
    router, _, _ = _router_bundle(tmp_path, conn, stt=stt)

    async def _allow_stub(
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

    monkeypatch.setattr(LLMGuardScanner, "scan_inbound", _allow_stub)

    raw = b"fake-audio"
    b64 = base64.b64encode(raw).decode("ascii")

    class _StubAdapter(ChannelAdapter):
        @property
        def name(self) -> str:
            return "stub"

        def parse_webhook(self, payload: dict[str, Any]) -> IncomingMessage | None:
            _ = payload
            return None

        async def send(self, message: OutgoingMessage) -> list[str]:
            _ = message
            return ["1"]

    router.register_adapter(_StubAdapter())
    msg = IncomingMessage(
        channel="stub",
        user_id="u-voice",
        text="",
        attachments=[
            {
                "type": "voice",
                "filename": "note.ogg",
                "data_base64": b64,
            },
        ],
        metadata={"chat_id": 9002},
    )
    await router.route_incoming(msg)
    await router.session_manager.drain()
    row = conn.execute(
        """
        SELECT extras_json FROM gateway_messages
        WHERE role = 'user' AND kind = 'message'
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    assert row is not None
    extras = json.loads(str(row[0]))
    assert extras.get("voice_user_text_last_turn") == "voice user said hi"
    conn.close()


@pytest.mark.asyncio
async def test_voice_user_text_last_turn_on_outbound_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent glue forwards persisted voice transcript on ``OutgoingMessage.metadata``."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    async def _fast(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text("Done.")

    async def _bundle_factory(_ws: WorkspaceConfig) -> ResolvedTierBModel:
        return ResolvedTierBModel(
            model_id="openai/gpt-voice",
            transport=_ScriptedChatTransport(_fast),
            budget=ModelBudget(model_id="openai/gpt-voice", regime=BudgetRegime.FREE_LOCAL),
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
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-voice",
            channel="telegram",
            user_id="u-voice",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content='[Voice message transcribed]: "voice user said hi"',
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps(
                {
                    "chat_id": 9002,
                    "voice_user_text_last_turn": "voice user said hi",
                }
            ),
            turn_id="t-test",
        )
        await run_turn(session_id, "corr-voice-1")
        await router.session_manager.drain()
        assert cap.sent_texts
        assert any(
            m.get("voice_user_text_last_turn") == "voice user said hi" for m in cap.outbound_meta
        )
    finally:
        conn.close()
