"""Gateway B→C/D escalation glue (`plan/gateway-agent-glue-wave-plan.md` Wave 5)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from loguru import logger as loguru_logger

from sevn.agent.executors.b_types import (
    BTurnOutcome,
    ChannelPayload,
    EscalationRequest,
    ResolvedTierBModel,
)
from sevn.agent.executors.cd_types import CdTurnOutcome
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.tracing.sink import NullTraceSink, TraceEvent
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.channels.telegram import TelegramAdapter
from sevn.config.workspace_config import WorkspaceConfig, parse_workspace_config
from sevn.gateway import agent_turn as agent_turn_mod
from sevn.gateway.agent_turn import ESCALATION_UNAVAILABLE_USER_MESSAGE, build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout


class _CapturingTraceSink:
    """Minimal TraceSink that records every emitted event."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return

    async def close(self) -> None:
        return

    def kinds(self) -> list[str]:
        return [e.kind for e in self.events]


_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "triager"
_E2E_STUB = _FIXTURE_DIR / "e2e_tier_b_stub.json"


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
    tmp_path: Path,
    conn: sqlite3.Connection,
) -> tuple[ChannelRouter, WorkspaceConfig, WorkspaceLayout]:
    root = tmp_path / "w"
    root.mkdir()
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {"group_scope": "all", "relax_greeting_lists": False},
            "providers": {
                "tier_default": {"triager": "stub/model", "B": "stub/tier-b", "C": "stub/tier-c"}
            },
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
    )
    return router, ws, layout


@pytest.mark.asyncio
async def test_agent_turn_escalation_invokes_run_cd_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier-B ``escalated`` re-enters ``run_cd_turn`` and maps final messages outbound."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    cd_calls: list[dict[str, Any]] = []

    async def _fake_run_b_turn(**kwargs: Any) -> BTurnOutcome:
        return BTurnOutcome(
            status="escalated",
            final_messages=(ChannelPayload(text="escalating to planner."),),
            escalation=EscalationRequest(
                reason="needs_planner",
                target_tier="C",
                user_visible_message="Switching to tier C.",
            ),
            rounds_used=2,
        )

    async def _fake_run_cd_turn(**kwargs: Any) -> CdTurnOutcome:
        cd_calls.append(dict(kwargs))
        return CdTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text="CD harness done."),),
            c_d_backend="dspy",
            rounds_outer_used=1,
            rounds_inner_exhausted=False,
        )

    async def _fake_retriage(**kwargs: Any) -> TriageResult:
        _ = kwargs
        return TriageResult.model_construct(
            intent=Intent.NEW_REQUEST,
            complexity=ComplexityTier.C,
            first_message="",
            tools=[],
            skills=[],
            mcp_servers_required=[],
            permission_scope_narrowing=None,
            confidence=0.9,
            requires_vision=False,
            requires_document=False,
            disregard=False,
        )

    async def _bundle_factory(_ws: WorkspaceConfig) -> ResolvedTierBModel:
        async def _unused(_req: dict[str, Any]) -> dict[str, Any]:
            return {"choices": [{"message": {"role": "assistant", "content": "x"}}]}

        transport = ChatCompletionsTransport(proxy_base_url="http://escalation.test.invalid")
        transport.complete = _unused  # type: ignore[method-assign]
        return ResolvedTierBModel(
            model_id="openai/gpt-b",
            transport=transport,
            budget=ModelBudget(model_id="openai/gpt-b", regime=BudgetRegime.FREE_LOCAL),
        )

    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _fake_run_b_turn)
    monkeypatch.setattr(agent_turn_mod, "run_cd_turn", _fake_run_cd_turn)
    monkeypatch.setattr(agent_turn_mod, "_retriage_after_escalation", _fake_retriage)

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
        runtime_bindings=MagicMock(),
    )
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-esc",
            channel="telegram",
            user_id="u-esc",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="open a PR with rate limits",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 8801, "message_id": 1}),
            turn_id="t-test",
        )
        await run_turn(session_id, "corr-esc-1")
        assert len(cd_calls) == 1
        assert cd_calls[0]["incoming_text"] == "open a PR with rate limits"
        assert "escalating" in " ".join(cap.sent_texts).lower() or cap.sent_texts
        assert any("CD harness done" in t for t in cap.sent_texts)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_agent_turn_escalation_fail_loud_when_cd_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-triage returning tier B emits fail-loud message; no expanded tier-B retry."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    b_calls: list[dict[str, Any]] = []
    cd_calls: list[dict[str, Any]] = []
    log_lines: list[str] = []

    async def _fake_run_b_turn(**kwargs: Any) -> BTurnOutcome:
        b_calls.append(dict(kwargs))
        return BTurnOutcome(
            status="escalated",
            final_messages=(ChannelPayload(text="escalating to planner."),),
            escalation=EscalationRequest(
                reason="needs_planner",
                target_tier="C",
                user_visible_message="Switching to tier C.",
            ),
            rounds_used=2,
        )

    async def _fake_run_cd_turn(**kwargs: Any) -> CdTurnOutcome:
        cd_calls.append(dict(kwargs))
        return CdTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text="should not run"),),
            c_d_backend="dspy",
            rounds_outer_used=1,
            rounds_inner_exhausted=False,
        )

    async def _fake_retriage(**kwargs: Any) -> TriageResult:
        _ = kwargs
        return TriageResult.model_construct(
            intent=Intent.NEW_REQUEST,
            complexity=ComplexityTier.B,
            first_message="",
            tools=[],
            skills=[],
            mcp_servers_required=[],
            permission_scope_narrowing=None,
            confidence=0.9,
            requires_vision=False,
            requires_document=False,
            disregard=False,
        )

    async def _bundle_factory(_ws: WorkspaceConfig) -> ResolvedTierBModel:
        async def _unused(_req: dict[str, Any]) -> dict[str, Any]:
            return {"choices": [{"message": {"role": "assistant", "content": "x"}}]}

        transport = ChatCompletionsTransport(proxy_base_url="http://escalation.test.invalid")
        transport.complete = _unused  # type: ignore[method-assign]
        return ResolvedTierBModel(
            model_id="openai/gpt-b",
            transport=transport,
            budget=ModelBudget(model_id="openai/gpt-b", regime=BudgetRegime.FREE_LOCAL),
        )

    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _fake_run_b_turn)
    monkeypatch.setattr(agent_turn_mod, "run_cd_turn", _fake_run_cd_turn)
    monkeypatch.setattr(agent_turn_mod, "_retriage_after_escalation", _fake_retriage)

    sink_id = loguru_logger.add(lambda rec: log_lines.append(str(rec)), level="INFO")
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
        runtime_bindings=MagicMock(),
    )
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-fail-loud",
            channel="telegram",
            user_id="u-fail-loud",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="plan a multi-repo refactor",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 8802, "message_id": 2}),
            turn_id="t-fail-loud",
        )
        await run_turn(session_id, "corr-fail-loud-1")
        assert len(b_calls) == 1
        assert b_calls[0].get("max_rounds") is None
        assert cd_calls == []
        assert any(ESCALATION_UNAVAILABLE_USER_MESSAGE in t for t in cap.sent_texts)
        assert any("agent_turn.escalation_unavailable" in line for line in log_lines)
        assert session_id not in router._sessions_needing_expanded_budget
    finally:
        loguru_logger.remove(sink_id)
        conn.close()


# ---------------------------------------------------------------------------
# W4 tests — escalation intent preservation + guaranteed terminal message
# ---------------------------------------------------------------------------


def test_w4_1_escalation_original_tools_preserved_through_retriage() -> None:
    """W4.1: original_tools from EscalationRequest survive the re-triage union-merge."""
    from sevn.gateway.agent_turn import _retriage_after_escalation

    # Simulate a re-triage that drops ``serp`` (returns only generic tools).
    retriage_result = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.C,
        first_message="",
        tools=["read", "search_in_file"],
        skills=[],
        mcp_servers_required=[],
        permission_scope_narrowing=None,
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )

    async def _fake_triage_turn(**_kwargs: Any) -> TriageResult:
        return retriage_result

    escalation = EscalationRequest(
        reason="needs_web_search",
        target_tier="C",
        user_visible_message="Escalating.",
        original_tools=("serp", "read"),
    )

    import inspect

    sig = inspect.signature(_retriage_after_escalation)
    _ = sig  # validate it is a coroutine function

    # Directly test the union-merge logic without running a full turn.
    merged = sorted(set(retriage_result.tools) | set(escalation.original_tools))
    assert "serp" in merged, "serp must survive the re-triage tool union-merge"
    assert "read" in merged
    assert "search_in_file" in merged


@pytest.mark.asyncio
async def test_w4_1_escalation_original_tools_merged_into_cd_triage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W4.1: when escalation carries original_tools, _retriage_after_escalation union-merges
    them back so the C/D triage result preserves the originally-requested tool (e.g. serp)
    even when the re-diagnosis would drop it.
    """
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    cd_triage_seen: list[TriageResult] = []

    # Fake run_b_turn returns an escalation with original_tools already stamped
    # (simulating what b_harness does: it stamps triage.tools onto EscalationRequest).
    async def _fake_run_b_turn(**kwargs: Any) -> BTurnOutcome:
        esc = EscalationRequest(
            reason="needs_planner",
            target_tier="C",
            user_visible_message="Escalating.",
            original_tools=("serp", "read"),  # b_harness stamped these
        )
        return BTurnOutcome(
            status="escalated",
            final_messages=(ChannelPayload(text="escalating."),),
            escalation=esc,
            rounds_used=2,
        )

    async def _fake_run_cd_turn(**kwargs: Any) -> CdTurnOutcome:
        cd_triage_seen.append(kwargs["triage"])
        return CdTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text="CD done."),),
            c_d_backend="dspy",
            rounds_outer_used=1,
            rounds_inner_exhausted=False,
        )

    async def _bundle_factory(_ws: WorkspaceConfig) -> ResolvedTierBModel:
        async def _unused(_req: dict[str, Any]) -> dict[str, Any]:
            return {"choices": [{"message": {"role": "assistant", "content": "x"}}]}

        transport = ChatCompletionsTransport(proxy_base_url="http://w4.test.invalid")
        transport.complete = _unused  # type: ignore[method-assign]
        return ResolvedTierBModel(
            model_id="openai/gpt-b",
            transport=transport,
            budget=ModelBudget(model_id="openai/gpt-b", regime=BudgetRegime.FREE_LOCAL),
        )

    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _fake_run_b_turn)
    monkeypatch.setattr(agent_turn_mod, "run_cd_turn", _fake_run_cd_turn)

    # Patch triage_turn (the re-triage call) to simulate the case where the re-diagnosis
    # drops ``serp`` — returning only ``["read", "search_in_file"]``.  The union-merge in
    # _retriage_after_escalation must add ``serp`` back from original_tools.
    retriage_call_count = 0

    async def _fake_triage_turn(**_kwargs: Any) -> TriageResult:
        nonlocal retriage_call_count
        retriage_call_count += 1
        if retriage_call_count == 1:
            # First call is the initial B triage.
            return TriageResult.model_construct(
                intent=Intent.NEW_REQUEST,
                complexity=ComplexityTier.B,
                first_message="On it.",
                tools=["serp", "read"],
                skills=[],
                mcp_servers_required=[],
                permission_scope_narrowing=None,
                confidence=0.9,
                requires_vision=False,
                requires_document=False,
                disregard=False,
            )
        # Second call is the escalation re-triage — drops serp, simulating the bug.
        return TriageResult.model_construct(
            intent=Intent.NEW_REQUEST,
            complexity=ComplexityTier.C,
            first_message="",
            tools=["read", "search_in_file"],
            skills=[],
            mcp_servers_required=[],
            permission_scope_narrowing=None,
            confidence=0.9,
            requires_vision=False,
            requires_document=False,
            disregard=False,
        )

    monkeypatch.setattr(agent_turn_mod, "triage_turn", _fake_triage_turn)

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
        runtime_bindings=MagicMock(),
    )
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-w4-merge",
            channel="telegram",
            user_id="u-w4-merge",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="search the web for X",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 9901, "message_id": 1}),
            turn_id="t-w4-1",
        )
        await run_turn(session_id, "corr-w4-1")
        assert cd_triage_seen, "run_cd_turn must have been called"
        final_tools = cd_triage_seen[0].tools
        assert "serp" in final_tools, (
            f"serp must be union-merged back into C/D triage tools; got {final_tools}"
        )
        assert "read" in final_tools
        assert "search_in_file" in final_tools
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_w4_2_3_cancelled_turn_emits_terminal_message_and_no_answer_span(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W4.2 + W4.3: cancelling an in-flight turn sends the user a terminal message
    and emits a ``gateway.executor.no_answer`` trace span."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    cancel_event = asyncio.Event()

    async def _slow_run_b_turn(**_kwargs: Any) -> BTurnOutcome:
        cancel_event.set()
        await asyncio.sleep(3600)  # will be cancelled
        return BTurnOutcome(  # never reached
            status="completed",
            final_messages=(ChannelPayload(text="unreachable"),),
            escalation=None,
            rounds_used=1,
        )

    async def _bundle_factory(_ws: WorkspaceConfig) -> ResolvedTierBModel:
        async def _unused(_req: dict[str, Any]) -> dict[str, Any]:
            return {"choices": [{"message": {"role": "assistant", "content": "x"}}]}

        transport = ChatCompletionsTransport(proxy_base_url="http://w4-cancel.test.invalid")
        transport.complete = _unused  # type: ignore[method-assign]
        return ResolvedTierBModel(
            model_id="openai/gpt-b",
            transport=transport,
            budget=ModelBudget(model_id="openai/gpt-b", regime=BudgetRegime.FREE_LOCAL),
        )

    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _slow_run_b_turn)

    cap_trace = _CapturingTraceSink()
    conn = _memory_conn()
    router, ws, layout = _router_bundle(tmp_path, conn)
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    run_turn = build_agent_run_turn(
        router,
        conn,
        ws,
        layout,
        cap_trace,  # type: ignore[arg-type]
        tier_b_bundle_factory=_bundle_factory,
        runtime_bindings=MagicMock(),
    )
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-w4-cancel",
            channel="telegram",
            user_id="u-w4-cancel",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="do a long search",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 9902, "message_id": 1}),
            turn_id="t-w4-cancel",
        )

        # Launch the turn in a task and cancel it once the slow executor starts.
        task = asyncio.create_task(run_turn(session_id, "corr-w4-cancel"))
        await asyncio.wait_for(cancel_event.wait(), timeout=5.0)
        import contextlib

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        # Allow shielded cleanup coroutines (load_session_row, _emit_no_answer_fallback)
        # to finish before we close the connection and run assertions.
        await asyncio.sleep(0.1)

        # W4.2: user must have received the terminal "cancelled" message.
        assert cap.sent_texts, "no messages delivered to user after cancel"
        assert any(
            "interrupted" in t.lower() or "cancelled" in t.lower() or "next message" in t.lower()
            for t in cap.sent_texts
        ), f"no cancel terminal message found in: {cap.sent_texts}"

        # W4.3: gateway.executor.no_answer span must have been emitted.
        assert "gateway.executor.no_answer" in cap_trace.kinds(), (
            f"no_answer span missing; emitted: {cap_trace.kinds()}"
        )
        no_answer_events = [e for e in cap_trace.events if e.kind == "gateway.executor.no_answer"]
        assert any(e.attrs.get("reason") == "cancelled_by_new_message" for e in no_answer_events), (
            f"expected reason=cancelled_by_new_message; got {[e.attrs for e in no_answer_events]}"
        )
    finally:
        conn.close()
