"""First-session intro scope and no double BOOTSTRAP (recovery Wave A)."""

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
from sevn.config.defaults import INITIAL_REGISTRY_VERSION
from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway import agent_turn as agent_turn_mod
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.onboarding.first_session import intro_state_for_scope, mark_intro_state
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
    """Minimal registry — full tool scan is not under test here."""
    _ = kwargs
    exe = TracingToolExecutor()
    tool_set = ToolSet(
        registry_version=INITIAL_REGISTRY_VERSION,
        native=(),
        mcp=(),
        skill_descriptions={},
    )
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
async def test_start_then_hi_single_intro_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/start`` bypass then ``hi`` runs BOOTSTRAP intro only on the agent turn."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))
    SkillsManager.reset_singletons_for_tests()
    conn = _memory_conn()
    router, ws, layout = _router_bundle(tmp_path, conn)
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    intro_flags: list[bool] = []
    b_turn_done = asyncio.Event()

    async def _fake_run_b_turn(**kwargs: Any) -> BTurnOutcome:
        extra = kwargs.get("extra_instructions") or ""
        intro_flags.append("FIRST_SESSION_INTRO" in extra)
        b_turn_done.set()
        return BTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text="Sevn reply."),),
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
                channel="telegram", user_id="u1", text="/start", metadata={"chat_id": 1}
            ),
        )
        await router.route_incoming(
            IncomingMessage(channel="telegram", user_id="u1", text="hi", metadata={"chat_id": 1}),
        )
        await asyncio.wait_for(b_turn_done.wait(), timeout=5.0)

        assert intro_flags == [True]
        assert intro_state_for_scope(conn, "telegram", "u1") == "in_flight"
    finally:
        await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_bootstrap_answers_turn_gets_capture_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Follow-up bootstrap answers enable capture instructions and write tool."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))
    conn = _memory_conn()
    router, ws, layout = _router_bundle(tmp_path, conn)
    from sevn.onboarding.seed import seed_narrative_templates

    seed_narrative_templates(
        layout.sevn_json_path,
        ws.model_dump(mode="json"),
        overwrite=False,
    )
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    capture_flags: list[str] = []
    bootstrap_tool_flags: list[bool] = []

    async def _fake_run_b_turn(**kwargs: Any) -> BTurnOutcome:
        extra = kwargs.get("extra_instructions") or ""
        if "FIRST_SESSION_INTRO" in extra:
            capture_flags.append("intro")
        elif "BOOTSTRAP_CAPTURE" in extra:
            capture_flags.append("capture")
        tool_set = kwargs.get("tool_set")
        names = {d.name for d in kwargs["tool_executor"].definitions()}
        bootstrap_tool_flags.append("write_workspace_md" in names)
        _ = tool_set
        return BTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text="Saved."),),
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

    sid = await router.session_manager.ensure_session(
        scope_key="telegram:u3",
        channel="telegram",
        user_id="u3",
    )
    mark_intro_state(conn, sid, "in_flight")
    await router.session_manager.add_message(
        sid,
        role="user",
        kind="message",
        content="hi",
        visible_to_llm=1,
        status="sent",
        metadata_blob=json.dumps({"chat_id": 3}),
        turn_id="t-test",
    )
    await router.session_manager.add_message(
        sid,
        role="user",
        kind="message",
        content="1. Alex\n2. casual\n3. AI engineer",
        visible_to_llm=1,
        status="sent",
        metadata_blob=json.dumps({"chat_id": 3}),
        turn_id="t-test",
    )
    await run_turn(sid, "corr-answers")
    await router.session_manager.drain()

    user_md = (layout.content_root / "USER.md").read_text(encoding="utf-8")
    assert "**Name:** Alex" in user_md
    assert intro_state_for_scope(conn, "telegram", "u3") == "done"
    conn.close()


@pytest.mark.asyncio
async def test_bootstrap_capture_before_triage_when_triager_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deterministic USER.md capture runs before triage, even when triage fails."""
    conn = _memory_conn()
    router, ws, layout = _router_bundle(tmp_path, conn)
    from sevn.agent.triager.errors import TriagerUnavailable
    from sevn.onboarding.seed import seed_narrative_templates

    seed_narrative_templates(
        layout.sevn_json_path,
        ws.model_dump(mode="json"),
        overwrite=False,
    )
    cap = _CaptureTelegram()
    router.register_adapter(cap)

    async def _fail_triage(**kwargs: Any) -> None:
        _ = kwargs
        raise TriagerUnavailable("triager down")

    monkeypatch.setattr(agent_turn_mod, "triage_turn", _fail_triage)
    run_turn = build_agent_run_turn(
        router,
        conn,
        ws,
        layout,
        NullTraceSink(),
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

    sid = await router.session_manager.ensure_session(
        scope_key="telegram:u5",
        channel="telegram",
        user_id="u5",
    )
    mark_intro_state(conn, sid, "in_flight")
    await router.session_manager.add_message(
        sid,
        role="user",
        kind="message",
        content="hi",
        visible_to_llm=1,
        status="sent",
        metadata_blob=json.dumps({"chat_id": 5}),
        turn_id="t-test",
    )
    await router.session_manager.add_message(
        sid,
        role="user",
        kind="message",
        content="call me Alex",
        visible_to_llm=1,
        status="sent",
        metadata_blob=json.dumps({"chat_id": 5}),
        turn_id="t-test",
    )
    await run_turn(sid, "corr-triage-fail")
    await router.session_manager.drain()

    user_md = (layout.content_root / "USER.md").read_text(encoding="utf-8")
    assert "**Name:** Alex" in user_md
    assert intro_state_for_scope(conn, "telegram", "u5") == "done"
    conn.close()


@pytest.mark.asyncio
async def test_bootstrap_im_alex_uses_tier_b_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bootstrap name answers persist before triage; tier B runs while USER.md fields remain."""
    conn = _memory_conn()
    router, ws, layout = _router_bundle(tmp_path, conn)
    from sevn.agent.triager.run import effective_triager_config, finalize_triage_result
    from sevn.onboarding.seed import seed_narrative_templates

    seed_narrative_templates(
        layout.sevn_json_path,
        ws.model_dump(mode="json"),
        overwrite=False,
    )
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    b_turn_called = False

    async def _fake_run_b_turn(**kwargs: Any) -> BTurnOutcome:
        _ = kwargs
        nonlocal b_turn_called
        b_turn_called = True
        return BTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text="Noted, Alex."),),
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

    from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult

    async def _triage_tier_a_then_finalize(**kwargs: Any) -> TriageResult:
        parsed = TriageResult.model_construct(
            intent=Intent.GREETING,
            complexity=ComplexityTier.A,
            first_message="Great to meet you, Alex!",
            tools=[],
            skills=[],
            mcp_servers_required=[],
            confidence=0.9,
            requires_vision=False,
            requires_document=False,
            disregard=False,
        )
        return finalize_triage_result(
            parsed=parsed,
            registry_snapshot=kwargs["registry_snapshot"],
            session=kwargs["session"],
            workspace=kwargs["workspace"],
            triager_cfg=effective_triager_config(kwargs["workspace"]),
            triage_context=kwargs["triage_context"],
        )

    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _fake_run_b_turn)
    monkeypatch.setattr(agent_turn_mod, "triage_turn", _triage_tier_a_then_finalize)
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

    sid = await router.session_manager.ensure_session(
        scope_key="telegram:u4",
        channel="telegram",
        user_id="u4",
    )
    mark_intro_state(conn, sid, "in_flight")
    await router.session_manager.add_message(
        sid,
        role="user",
        kind="message",
        content="hi",
        visible_to_llm=1,
        status="sent",
        metadata_blob=json.dumps({"chat_id": 4}),
        turn_id="t-test",
    )
    await router.session_manager.add_message(
        sid,
        role="user",
        kind="message",
        content="I'm Alex",
        visible_to_llm=1,
        status="sent",
        metadata_blob=json.dumps({"chat_id": 4}),
        turn_id="t-test",
    )
    await run_turn(sid, "corr-tier-b-name")
    await router.session_manager.drain()

    assert b_turn_called is True
    user_md = (layout.content_root / "USER.md").read_text(encoding="utf-8")
    assert "**Name:** Alex" in user_md
    assert intro_state_for_scope(conn, "telegram", "u4") == "done"
    conn.close()


@pytest.mark.asyncio
async def test_new_session_after_onboarded_skips_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh session for an onboarded ``(channel, user_id)`` does not re-intro."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))
    conn = _memory_conn()
    router, ws, layout = _router_bundle(tmp_path, conn)
    (layout.content_root / "USER.md").write_text("Name: Alex\n", encoding="utf-8")
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    intro_flags: list[bool] = []

    async def _fake_run_b_turn(**kwargs: Any) -> BTurnOutcome:
        extra = kwargs.get("extra_instructions") or ""
        intro_flags.append("FIRST_SESSION_INTRO" in extra)
        return BTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text="Follow-up."),),
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

    sid1 = await router.session_manager.ensure_session(
        scope_key="telegram:u2",
        channel="telegram",
        user_id="u2",
    )
    mark_intro_state(conn, sid1, "done")
    sid2 = await router.session_manager.ensure_session(
        scope_key="telegram:u2-new",
        channel="telegram",
        user_id="u2",
    )
    assert sid2 != sid1
    await router.session_manager.add_message(
        sid2,
        role="user",
        kind="message",
        content="hi again",
        visible_to_llm=1,
        status="sent",
        metadata_blob=json.dumps({"chat_id": 2}),
        turn_id="t-test",
    )
    await run_turn(sid2, "corr-new")
    await router.session_manager.drain()

    assert intro_flags == [False]
    conn.close()
